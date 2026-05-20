# Phase 1 Execution Plan: Boundary And Golden Fixture Preparation

## Metadata

- Status: draft phase execution plan
- Feature focus: Config Extraction
- PR title: `Config Extraction - Phase 1: Boundary and Golden Fixtures`
- Branch: `codex/config-boundary-golden-fixtures`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-boundary-golden-fixtures`
- Phase execution plan path: `docs/roadmap/stage-23/phases/config-boundary-golden-fixtures.md`
- Full plan: `docs/roadmap/stage-23/implementation-plan.md`
- Planning artifact: `docs/roadmap/stage-23/planning.md`
- Source phase: Stage 23 Phase 1, Boundary And Golden Fixture Preparation
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible only after automated review, required validation, and CI pass while targeting `develop`; phase agents must not merge.
- Workflow path: expanded path
- Successor dependency notes: Phase 2 should branch from updated `develop` after this phase merges. If GitHub-side blockers leave this PR open, Phase 2 may stack on `codex/config-boundary-golden-fixtures` only after this phase is opened or prepared, validated, and recorded as `pr_open`.
- Plan quality gate: passed on 2026-05-20 in the implementation plan, with no blocking findings after confirmation review.
- Plan quality gate loop budget: consumed and passed before this phase plan; do not rerun unless the manager explicitly reopens the stage plan.
- Draft pass: completed in this artifact.
- Refine pass: required by expanded path but not yet run in this draft; use one bounded refinement pass before implementation if the manager continues the expanded-path workflow.
- Setup limitations: branch was created from local `origin/develop`/`develop` at `7d9235d`; no network fetch was performed. Initial worktree creation needed sandbox escalation because git refs live in the control checkout metadata.
- Blockers: none for drafting; implementation must stop if golden artifact output is not deterministic through public APIs or requires private implementation hooks.

## Objective

Pin current config artifact behavior and current import-boundary facts before any `weave` package scaffold, config implementation movement, or Loom adapter rewiring begins.

## Full-Plan Context

Stage 23 extracts trusted config authoring from `loom.config` into the standalone `weave` distribution while preserving deterministic config artifacts unless a break is explicitly accepted. This phase creates the baseline evidence that later package scaffold, implementation port, hard switch, test/example relocation, and docs hardening phases must preserve. It must not create `packages/weave`, move config modules, change public import paths, rewire Loom adapters, or introduce package metadata.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: the implementation plan records Phase 1 as the first Stage 23 phase, based on `develop`; local `develop` and `origin/develop` both resolve to `7d9235d`.
- Retarget/rebase plan after predecessor merge: not applicable for this root phase.
- Branch cleanup constraints: branch may be deleted after the phase PR is merged and no successor branch depends on it; keep it if a stacked successor is created before merge.

## Source Phase Summary

- Goal: pin current config artifact behavior and import-boundary facts before package movement.
- Required scope: add root test fixtures, root golden expected-output files, a contract test for public config artifact outputs, and targeted import-boundary assertions or TODO-backed current-state assertions.
- Required checkpoints: golden artifacts are generated or compared through public config APIs, structured config errors are captured without private traceback coupling, and boundary tests make Phase 4's allowed/disallowed imports explicit.
- Acceptance criteria: targeted golden contract, import-boundary test, contract suite, and repository validation obligations are satisfied or any inability to run them is recorded by the executor and PR preparer.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: current config APIs live in `src/loom/config/api.py`, with artifact records in `src/loom/config/artifacts.py`, fingerprints in `src/loom/config/fingerprints.py`, provenance in `src/loom/config/provenance.py`, and recipe manifest records in `src/loom/config/recipes/manifest.py`.
- Existing tests or harness behavior: config contracts already cover artifact record round trips, composition inspection shape, structured config error payloads, recipe contracts, and import boundaries under `tests/contracts/` and `tests/package/test_import_boundaries.py`.
- Import-boundary or dependency constraints: `import loom`, core runtime imports, executor command imports, and `loom.io` must stay cheap and must not eagerly import config-only optional dependencies. Phase 1 may record current `loom.config` import behavior, but must not introduce `weave` imports.

## In-Scope Work

- Add a compact, domain-neutral authored config fixture project at `tests/fixtures/config/golden_project/`.
- Add expected golden JSON files under `tests/golden/config/extraction-v23/` for resolved config, redacted config, composition manifest, recipe manifest, source artifact records, raw source snapshots, config fingerprint record, and structured config errors.
- Add `tests/contracts/test_config_extraction_golden_artifacts_contract.py` using public config APIs such as `inspect_config_composition`, `compose_config`, and public error serialization surfaces.
- Extend `tests/package/test_import_boundaries.py` with current-state or TODO-backed assertions that document the Phase 4 target boundary without forcing the later hard switch early.
- Use deterministic fixture values and relative or normalized paths where public APIs expose local paths, so expected files remain reviewable across machines.
- Record any deterministic artifact mismatch as a blocker before implementation movement.

## Out-of-Scope Work

- Creating `packages/weave` or adding `weave` package metadata.
- Moving, copying, or rewriting `src/loom/config` implementation modules.
- Rewriting user imports from `loom.config` to `weave`.
- Adding a `loom.config` compatibility shim.
- Changing config semantics, recipe behavior, redaction policy, include resolution, fingerprint policy, or error schema.
- Moving config tests or examples into package-local locations.
- Updating PR body artifacts or opening a PR.

## Assumptions

- Existing config unit, integration, and contract tests already cover semantic behavior; this phase adds durable artifact-shape baselines.
- Golden fixtures can be built with synthetic, domain-neutral authored config values and a tiny test-local recipe or target object if recipe and `_target_` coverage need one.
- Current path-bearing artifact outputs can be normalized or asserted through public output fields without hiding meaningful schema drift.
- Optional config dependencies are available in the expected config-enabled test environment used by `test-config-extra`, `test-contract`, and `validate-pr`.

## Scope Contract

No new public runtime API or package import path is in scope. The contract this phase introduces is a test-data contract: current `loom.config` public APIs define the baseline serialized shapes for the eight golden artifact families named by the implementation plan. Later phases must either match these files exactly or record an explicit accepted break, rationale, migration note, and fixture update review.

The structured-error fixture should serialize public error payloads, including stable message/context fields, without asserting traceback text, exception module identity, or private helper names. Import-boundary assertions should clarify that current `loom.config` exists only as the pre-extraction baseline and that future `weave` boundaries belong to later phases.

## Design Impact

- Maintainability: gives later package movement a small reviewed baseline instead of relying on ad hoc comparisons during the hard switch.
- Extensibility: keeps fixture inputs and expected outputs movable to `packages/weave/tests` in Phase 5.
- Domain neutrality: fixture names and values must stay synthetic and avoid dataset, model, metric, report, or checkpoint semantics.
- Source-tree boundaries: all work stays in root tests and golden fixtures because `weave` does not exist yet.

## Future Compatibility

- Phase 3 and Phase 4 must run the golden contract against the extracted implementation to catch artifact drift.
- Phase 5 can move or mirror the same fixture project and expected outputs into package-local paths.
- The fixture file names and public artifact families should remain stable so PR reviewers can identify intentional versus accidental changes.
- Import-boundary checks added here should be phrased so Phase 4 can flip them from current baseline to final prohibition without losing historical intent.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Wait until after the `weave` port to add golden fixtures | Would allow artifact drift during movement with no reviewed baseline. |
| Generate golden outputs dynamically without checked-in expected files | Would test only self-consistency, not extraction compatibility. |
| Use private config implementation helpers to produce fixture artifacts | Would couple the baseline to code that later phases are explicitly moving. |
| Cover all config semantics in this golden contract | Existing unit/integration suites own semantic breadth; this phase should pin durable artifact shapes only. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Temporary root-owned golden fixtures for config package behavior | `weave` does not exist in Phase 1, so fixtures must run against current `loom.config`. | Phase 5 moves or mirrors fixtures under `packages/weave/tests`. |
| Current-state import-boundary assertions may mention future `weave` TODOs | Phase 1 cannot enforce final boundaries before the package exists. | Phase 4 creates `weave` adapter imports and removes `src/loom/config`. |
| Golden files may include normalized path placeholders | Public artifact records contain local file paths, and checked-in fixtures must be portable. | A public artifact schema gains stable project-relative paths or the normalization masks meaningful differences. |

## Reviewability

- Expected PR size and shape: focused test-only PR with one fixture project, one golden expected-output directory, one contract test, and a narrow import-boundary test update.
- Files and areas to inspect: `tests/fixtures/config/golden_project/`, `tests/golden/config/extraction-v23/`, `tests/contracts/test_config_extraction_golden_artifacts_contract.py`, and `tests/package/test_import_boundaries.py`.
- Scope-control checks: no changes under `src/loom/config`, no `packages/weave`, no package metadata changes, no docs rewrite beyond execution-plan metadata if the manager explicitly assigns it later.

## Implementation Steps

1. Create the minimal fixture project that exercises overlays, includes or replacement, overrides, recipe expansion, redaction, provenance, source records, raw source snapshots, and artifact-safe fingerprint records through public config APIs.
2. Add the golden contract test and expected JSON files, with deterministic serialization and portable handling for path-bearing fields.
3. Add a structured-error scenario whose serialized payload locks stable user-facing context fields without coupling to traceback or private helper details.
4. Extend import-boundary tests to document current pre-extraction imports and Phase 4's allowed/disallowed target boundary without importing `weave`.
5. Run targeted validation, update fixtures only for reviewed deterministic output, and stop if any artifact family cannot be produced or compared through public APIs.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: root package import and boundary tests must remain green; new assertions should document current `loom.config` behavior and future `weave` boundary expectations without enforcing non-existent package imports.

### Unit Suite

- Status: deferred
- Expected paths: existing `tests/unit/loom/config/**`
- Required assertions or deferral reason: Phase 1 should not add broad semantic unit coverage unless a tiny helper inside the new contract test needs factoring; existing config unit suites remain unchanged.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_config_extraction_golden_artifacts_contract.py`
- Required assertions or deferral reason: compare checked-in stable JSON for all eight artifact families and verify structured config error payload shape through public serialization.

### Integration Suite

- Status: deferred
- Expected paths: existing `tests/integration/config/**`
- Required assertions or deferral reason: no adapter or workflow behavior changes are in scope; existing integration tests should continue passing through `make validate-pr`.

### E2E Suite

- Status: deferred
- Expected paths: existing `tests/e2e/**`
- Required assertions or deferral reason: no CLI or end-to-end workflow behavior changes are in scope; e2e coverage is indirect through final `make validate-pr`.

### Opt-In Suites

- Status: required
- Markers affected: `contract`, `package`, and existing optional config dependency markers when the new contract requires OmegaConf, PyYAML, or Pydantic.
- Required assertions or deferral reason: the targeted golden contract should skip or mark optional config dependencies consistently with nearby config contracts, and `make test-contract` should include it.

## Risks

- Golden fixture output may expose undocumented current artifact drift or path instability.
- Structured error payloads may include class/module identity that will change after the hard switch; only user-facing payload fields should be treated as stable.
- A broad fixture can accidentally become a config semantic test suite; keep it compact and artifact-focused.
- Import-boundary TODOs can become stale if they are not paired with executable current-state checks.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py
uv run pytest tests/package/test_import_boundaries.py
make test-contract
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: fixture project plus expected files; golden contract test; import-boundary update; targeted validation and fixture review.
- Tests to run with each slice: run the new contract test after fixture changes, run import-boundary tests after boundary edits, run `make test-contract` before final PR preparation, and leave `make validate-pr`/`make test-summary` for PR preparation evidence if the phase executor does not run the final full gate.
- Decisions the executor must not revisit: no `weave` package, no `loom.config` shim, no config semantics changes, no private helper coupling, and no accepted artifact break without manager direction.
- Conditions that require stopping for the manager: nondeterministic public artifact output, need for private implementation hooks, inability to normalize path-bearing fields without losing meaningful contract data, or any mismatch suggesting a current artifact bug that should be fixed before extraction.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this commit.
- Refine plan: pending expanded-path refine pass; not run in this draft.
- Final phase execution plan: pending.
- Implementation summary: not started.
- Implementation validation: not run.
- Refinement summary: unused.
- Blocker-resolution summary: unused.
- PR preparation: not started.
- Stack maintenance: branch created from `origin/develop`; no predecessor.
- Remaining blockers: none for planning.
