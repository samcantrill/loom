# Phase 1 Execution Plan: Boundary And Golden Fixture Preparation

## Metadata

- Status: refined phase execution plan; ready for implementation
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
- Refine pass: completed in this artifact; expanded-path planning budget is consumed for this phase unless the manager explicitly reopens planning.
- Setup limitations: branch was created from local `origin/develop`/`develop` at `7d9235d`; no network fetch was performed. Initial worktree creation needed sandbox escalation because git refs live in the control checkout metadata.
- Blockers: none; implementation must stop if golden artifact output is not deterministic through public APIs, requires private implementation hooks, or cannot be made portable without hiding meaningful artifact data.

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
- Existing tests or harness behavior: config contracts already cover artifact record round trips, composition inspection shape, structured config error payloads, recipe contracts, raw source snapshot behavior, and import boundaries under `tests/contracts/`, `tests/integration/config/`, and `tests/package/test_import_boundaries.py`.
- Public API constraints: golden generation should use `loom.config.inspect_config_composition(...)` or `compose_config(...)` with public `RecipeCatalog` wiring and `include_raw_source_snapshots=True` when snapshot payloads are expected. Serialization should use public object fields and public `to_dict()` methods.
- Import-boundary or dependency constraints: `import loom`, core runtime imports, executor command imports, and `loom.io` must stay cheap and must not eagerly import config-only optional dependencies. Phase 1 may record current `loom.config` import behavior, but must not introduce `weave` imports or require `weave` to exist.

## In-Scope Work

- Add a compact, domain-neutral authored config fixture project at `tests/fixtures/config/golden_project/`.
- Add expected golden JSON files under `tests/golden/config/extraction-v23/` for resolved config, redacted config, composition manifest, recipe manifest, source artifact records, raw source snapshots, config fingerprint record, and structured config errors.
- Add `tests/contracts/test_config_extraction_golden_artifacts_contract.py` using public config APIs such as `inspect_config_composition`, `compose_config`, `RecipeCatalog`, public record `to_dict()` methods, and public error serialization surfaces.
- Extend `tests/package/test_import_boundaries.py` with executable current-state assertions that document Phase 4's target boundary without forcing the later hard switch early.
- Use deterministic fixture values and relative or placeholder-normalized paths where public APIs expose local paths, so expected files remain reviewable across machines.
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
- Golden fixtures can be built with synthetic, domain-neutral authored config values and a tiny test-local recipe or target object if recipe and `_target_` coverage need one; avoid importing downstream project packages.
- Current path-bearing artifact outputs can be normalized or asserted through public output fields without hiding meaningful schema drift.
- Optional config dependencies are available in the expected config-enabled test environment used by `test-config-extra`, `test-contract`, and `validate-pr`.

## Scope Contract

No new public runtime API or package import path is in scope. The contract this phase introduces is a test-data contract: current `loom.config` public APIs define the baseline serialized shapes for the eight golden artifact families named by the implementation plan. Later phases must either match these files exactly or record an explicit accepted break, rationale, migration note, and fixture update review.

The structured-error fixture should serialize public error payloads, including stable message/context fields, without asserting traceback text, exception module identity, or private helper names. Import-boundary assertions should clarify that current `loom.config` exists only as the pre-extraction baseline and that future `weave` boundaries belong to later phases.

### Golden Artifact Public API Contract

- `resolved-config.json`: take `inspection.resolved` from `loom.config.inspect_config_composition(...)`.
- `redacted-config.json`: take `inspection.redacted` from the same inspection and include at least one secret-like key whose value is redacted by the public redaction policy.
- `composition-manifest.json`: take `inspection.manifest.to_dict()`.
- `recipe-manifest.json`: take `list(inspection.recipe_manifest)`, produced through a public `RecipeCatalog` and a test-local recipe implementation.
- `source-artifact-records.json`: serialize `[record.to_dict() for record in inspection.source_artifacts]`.
- `raw-source-snapshots.json`: serialize `inspection.raw_source_snapshots.to_dict()` from a public call with `include_raw_source_snapshots=True`.
- `config-fingerprint-record.json`: serialize the artifact-safe record from `inspection.fingerprint_records`; the expected file should include label, algorithm, digest, and metadata shape.
- `structured-config-errors.json`: serialize one public config error payload via `.to_dict()`, preferably from a deterministic public failure path such as an unresolved include, invalid include payload, unsupported resolver, or malformed authored YAML.

Use `inspect_config_composition` as the primary source because it exposes unresolved, resolved, redacted, provenance, recipe manifest, source artifact, fingerprint, and snapshot records in one public result. Use `compose_config` only when the executor needs to confirm parity with the public composed-config convenience result. Do not call private helpers from `src/loom/config/compose.py`, `source_maps.py`, `includes.py`, `fingerprints.py`, or `artifacts.py` directly from the golden contract.

### Path Normalization Contract

- Normalize absolute paths that point inside `tests/fixtures/config/golden_project/` to a stable placeholder root such as `<golden_project>/...`.
- Apply normalization consistently to `source_artifacts[*].path`, raw source snapshot `references[*].path`, provenance or manifest metadata that repeats source paths, and structured-error context fields such as `source_path`, `candidate_path`, `resolved_path`, or path-bearing `details`.
- Preserve authored relative include strings, config paths such as `$.pipeline.model._include_`, source kinds, orders, sizes, content digests, payload IDs, availability, and reasons.
- Do not normalize digest fields, fingerprint digests, schema versions, labels, algorithms, metadata keys, source order, source kind, or redaction output.
- If a digest changes only because absolute path text leaked into a hashed public payload, stop and report the blocker instead of normalizing the digest independently.

### Structured Error Stability Contract

- Stable fields: `message`, `context.code`, `context.source_kind`, `context.source_order`, normalized `context.source_path`, `context.config_path`, `context.expected`, `context.actual`, `context.directive`, `context.remediation`, and plain-data `context.details`.
- Unstable fields to avoid: traceback text, exception repr, concrete Python module/class identity, object memory addresses, private helper function names, and filesystem temp-directory prefixes.
- The test should assert that `ConfigErrorContext.from_dict(payload["context"])` round-trips when the selected error payload includes context.
- The selected error scenario should be deterministic from checked-in fixture files, not from the caller's current working directory or host-specific environment variables.

### Import-Boundary Current-State Assertions

- Keep existing checks that `import loom`, `import loom.io`, `import loom.pipeline`, executor command imports, and other core imports do not eagerly import `loom.config`, config-only optional dependencies, CLI modules, or heavy runtime layers.
- Add current-state checks that `import loom.config` is still allowed in Phase 1 and does not import pipeline execution, executors, stores, CLI, or other runtime internals.
- Add a current-state inventory test or table-driven assertion for the final Phase 4 boundary: allowed future adapter modules may import config composition, while forbidden runtime areas must not import config composition internals. In Phase 1 this should be documentation-backed or current-state executable only; it must not import or require `weave`.
- Do not add a failing `weave` import-boundary test before Phase 2 creates the package.

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
- Golden files should be shaped so Phase 5 can relocate them with only path-root changes, not schema or fixture redesign.

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
- Golden review checks: fixture inputs are domain-neutral, expected JSON is deterministic and sorted, path normalization rules are explicit in the test, and every expected file maps to one of the eight required artifact families.
- Scope-control checks: no changes under `src/loom/config`, no `packages/weave`, no package metadata changes, no PR body, and no docs rewrite beyond execution-plan metadata if the manager explicitly assigns it later.

## Implementation Steps

1. Create the minimal fixture project that exercises overlays, includes or replacement, ordinary overrides, recipe expansion through `RecipeCatalog`, redaction, provenance, source records, raw source snapshots, and artifact-safe fingerprint records through public config APIs.
2. Add a small normalization/rendering layer inside the contract test that converts public objects to stable JSON payloads, including placeholder-normalized fixture-root paths and sorted object keys.
3. Add expected JSON files for each required artifact family and compare them exactly from the public inspection result.
4. Add a structured-error scenario whose serialized payload locks stable user-facing context fields and round-trippable `ConfigErrorContext` data without coupling to traceback or private helper details.
5. Extend import-boundary tests to document current pre-extraction imports and Phase 4's allowed/disallowed target boundary without importing `weave`.
6. Run targeted validation, update fixtures only for reviewed deterministic output, and stop if any artifact family cannot be produced or compared through public APIs.

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
- Required assertions or deferral reason: compare checked-in stable JSON for all eight artifact families, verify structured config error payload shape through public serialization, and assert path normalization preserves public contract fields while removing host-specific absolute fixture roots.

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
- Markers affected: `contract`, `package`, and `optional_dependency` when the new contract requires OmegaConf, PyYAML, or Pydantic.
- Required assertions or deferral reason: the targeted golden contract should skip or mark optional config dependencies consistently with nearby config contracts, and `make test-contract` should include it.

## Risks

- Golden fixture output may expose undocumented current artifact drift or path instability.
- Structured error payloads may include class/module identity that will change after the hard switch; only user-facing payload fields should be treated as stable.
- A broad fixture can accidentally become a config semantic test suite; keep it compact and artifact-focused.
- Import-boundary TODOs can become stale if they are not paired with executable current-state checks.
- Over-normalizing path-bearing payloads can hide real schema drift; normalize only host-specific fixture-root prefixes and leave semantic path data intact.

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
- Tests to run with each slice: run the new contract test after fixture and expected-file changes, run import-boundary tests after boundary edits, run `make test-contract` before final PR preparation, and leave `make validate-pr`/`make test-summary` for PR preparation evidence if the phase executor does not run the final full gate.
- Decisions the executor must not revisit: no `weave` package, no `loom.config` shim, no config semantics changes, no private helper coupling, and no accepted artifact break without manager direction.
- Conditions that require stopping for the manager: nondeterministic public artifact output, need for private implementation hooks, inability to normalize path-bearing fields without losing meaningful contract data, digest drift caused by host-specific paths, or any mismatch suggesting a current artifact bug that should be fixed before extraction.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this commit.
- Refine plan: completed by expanded-path refinement in this commit.
- Final phase execution plan: ready for implementation after this refinement.
- Implementation summary: added `tests/fixtures/config/golden_project/{base,overlay,include,broken}.yaml`, generated and normalized `tests/golden/config/extraction-v23/{resolved-config.json, redacted-config.json, composition-manifest.json, recipe-manifest.json, source-artifact-records.json, raw-source-snapshots.json, config-fingerprint-record.json, structured-config-errors.json}`, added `tests/contracts/test_config_extraction_golden_artifacts_contract.py` using public `loom.config` APIs and error serialization, and added current-state boundary assertions to `tests/package/test_import_boundaries.py`.
- Implementation validation: contract test `UV_CACHE_DIR=/tmp/uv-cache uv run --active pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py` passed; package boundary test `UV_CACHE_DIR=/tmp/uv-cache uv run --active pytest tests/package/test_import_boundaries.py` passed; `UV_CACHE_DIR=/tmp/uv-cache uv run make test-contract` passed when executed with approved network access. `make test-summary` was not completed in this environment due long-running/no-output execution behavior.
- Refinement summary: target-module normalization was adjusted by setting helper recipe `annotate.__module__` to `test_config_extraction_golden_artifacts_contract` for deterministic artifact fingerprints across test invocation contexts.
- Blocker-resolution summary: unused.
- PR preparation: not started.
- Stack maintenance: branch created from `origin/develop`; no predecessor.
- Remaining blockers: none.
