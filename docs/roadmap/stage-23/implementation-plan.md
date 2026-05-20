# Roadmap Stage 23 Implementation Plan: Standalone Config Package Extraction

Status: complete; all phases merged
Roadmap stage: `v23`
Planning document: `docs/roadmap/stage-23/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: complete
Blockers:

- None for roadmap-stage planning readiness.
- None for implementation-plan quality; `loom_plan_reviewer` confirmation
  review passed on 2026-05-20.
- Phase 1 execution plan drafted, refined, executed, reviewed, opened,
  validated, and merged.
- Phase 2 execution plan drafted, refined, executed, reviewed, opened,
  validated, and merged.
- Phase 3 execution plan drafted, refined, executed, reviewed, opened,
  validated, and merged.
- Phase 4 execution plan drafted, refined, executed, reviewed, opened,
  validated, and merged.
- Phase 5 execution plan drafted, refined, executed, reviewed, opened,
  validated, and merged.
- Phase 6 execution plan drafted, refined, implemented, reviewed, opened,
  validated, merged, and cleaned up.

## Summary

- Goal: hard-switch trusted config authoring out of `loom` into a standalone
  `weave` distribution with import package `weave`, while keeping
  Loom as the workflow/runtime package that depends on config only through
  explicit adapter paths.
- Source functionality-agreement gate:
  `docs/roadmap/stage-23/planning.md`; requirements FR-1 through FR-6 are
  confirmed.
- Approved behavior: direct config users import `weave`; Loom CLI/Python
  config workflows continue through explicit adapter paths; config-owned tests
  and examples move beside the config package; config artifact behavior remains
  golden-test stable unless an implementation decision explicitly accepts a
  break.
- Source behavior confirmation: user confirmed the behavior baseline on
  2026-05-20 and approved continuing through implementation-plan drafting on
  2026-05-20.
- Key design constraints: no `loom.config` compatibility shim by default,
  `weave` imports no `loom`, Loom keeps runtime-required serialization,
  fingerprinting, error, and override-validation behavior, and package-owned
  duplicated helper implementations are preferred over a new shared core.
- Source design-agreement gate: completed in the planning artifact; DAQ-1
  through DAQ-10 are confirmed.
- Future-roadmap impact: the package-local source, tests, examples, dependency
  metadata, and validation commands should be movable into a future standalone
  `weave` repository without pulling Loom runtime internals with them.
- Reusable interface, adapter, or protocol assumptions: Loom config adapter
  paths call `weave` and hand plain data plus explicit config records to
  runtime code; runtime internals do not import config composition internals or
  config-package helper modules for functionality Loom owns.
- Examples covered: config composition, overlays, includes, replacement,
  recipes, target instantiation, redaction, provenance, artifact safety,
  config fingerprints, and structured config errors move to
  `packages/weave/examples`; Loom examples remain workflow/runtime
  examples and import `weave` only as an authored-config frontend where
  needed.
- Source phase shaping: six-phase shape from the planning artifact, refined
  here into reviewable PR boundaries.
- Source plan quality gate: passed on 2026-05-20 after one refinement pass and
  confirmation review.
- Out of scope: separate repository publication, `loom.config` shim, Hydra
  bridge, new config semantics, untrusted-config sandboxing, broad Loom runtime
  redesign, and splitting Loom runtime into additional distributions.

## Implementation Workflow State

- Implementation-plan quality gate: passed on 2026-05-20
- Review pass: completed on 2026-05-20 by `loom_plan_reviewer`; blocked on
  package metadata ownership and plugin diagnostics boundary omissions
- Refinement pass: completed on 2026-05-20 in this implementation-plan draft
- Confirmation review: completed on 2026-05-20 by `loom_plan_reviewer`; passed
  with no blocking findings
- Post-gate naming update: user renamed the config package to `weave` on
  2026-05-20; this changes package/distribution/import names only and does not
  reopen the responsibility split, hard-switch policy, helper-ownership
  decision, or phase structure
- Automatic merge mode: enabled after plan quality gate and each phase PR gate
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-23/planning.md`
- Functionality and behavior baseline: confirmed.
- Design agreement: resolved, with no unresolved `needs discussion` or blocked
  decisions.
- Design-safety review: passed on 2026-05-20.
- Examples and validation strategy: reviewed by design-safety; this plan fixes
  fixture locations and validation target names for phase planning.
- Phase shaping: reviewed by design-safety; this plan keeps six reviewable
  phases.
- Implementation-plan drafting approval: user explicitly approved drafting on
  2026-05-20.
- Implementation readiness blockers:
  - None for drafting this plan.
  - Phase execution must wait for the plan quality gate.

## Desired Outcome

When all phases are complete:

- `packages/weave` is an independently installable package with
  `pyproject.toml`, `src/weave`, `py.typed`, package-local tests, and
  package-local examples.
- `weave` owns config composition, overlays, includes, replacement,
  overrides, recipes, `_target_` instantiation, redaction, provenance,
  composition manifests, source artifact records, raw source snapshots, config
  fingerprints, and config error types.
- `weave` owns config-specific plain-data, stable JSON, digest,
  fingerprint, and error helpers, and imports no `loom` modules.
- Loom owns pipeline specs, planning, execution, stores, authority, queueing,
  run catalogs, bundles, runtime events, cleanup, CLI orchestration, and
  runtime-required helper behavior.
- Loom config adapter paths depend on `weave`; runtime internals consume
  composed plain data and explicit config records rather than config
  composition internals.
- `src/loom/config` is removed as a runtime implementation path and there is no
  default `loom.config` compatibility shim.
- Config-owned tests and examples live under `packages/weave`.
- Root Loom tests continue to cover workflow/runtime behavior, including CLI
  workflows that use authored config through adapter paths.
- Golden fixtures prove the extraction preserves deterministic config artifact
  shapes unless a break is explicitly accepted.
- `make validate-pr` and `make test-summary` report both root Loom and
  package-local config evidence by the final phase.

## What This Means In Practice

The extraction should be staged to keep every PR reviewable and green:

- First pin the current artifact behavior before moving implementation code.
- Then add the package shell and config-owned helper modules without changing
  Loom runtime behavior.
- Then port config implementation into `weave` while the old in-tree
  implementation still exists only as a temporary migration baseline.
- Then hard-switch Loom adapter paths, remove `src/loom/config`, and enforce
  import boundaries.
- Then relocate tests and examples so future repository extraction does not
  need to discover ownership again.
- Finally update docs and validation so the repository describes the new
  package boundary rather than the old in-tree subsystem.

The temporary duplicate implementation between the package port and the hard
switch is accepted only as a short phase-to-phase migration tactic. The final
stage state must not keep two config implementations.

## Non-Goals

- No compatibility shim for `from loom.config import ...` in the final stage
  state.
- No new config language features.
- No Hydra compatibility layer.
- No untrusted-config sandboxing.
- No runtime workflow redesign beyond adapter rewiring and import-boundary
  cleanup required by the extraction.
- No separate repository publication.
- No shared-core utility package.
- No domain-specific examples, recipes, stages, or schemas.

## Constraints

- Follow `docs/structure.md` and `docs/GLOSSARY.md`.
- Keep Loom domain-neutral.
- Treat authored configs as trusted project code.
- Do not introduce heavyweight runtime dependencies beyond the dependencies
  already required by the config layer.
- `weave` must not import `loom`.
- Loom runtime internals must not import config composition internals.
- Loom runtime-required serialization, fingerprinting, and error functionality
  stays Loom-owned even when `weave` has equivalent config-specific
  helper behavior.
- Config package tests and examples must be runnable from package-local paths.
- Existing deterministic config artifact shapes must remain stable unless a
  break is recorded with rationale and a migration note.

## Design Principles

- Separate ownership before optimizing reuse. Duplicate small helper behavior
  where both packages need equivalent semantics.
- Make adapter boundaries visible. Loom may import `weave` only where it
  is explicitly consuming authored config.
- Preserve config semantics. This is a package extraction stage, not a config
  language stage.
- Pin durable artifacts before moving their implementation.
- Keep phases reviewable. Avoid a single large "move everything" PR.
- Keep validation local and dependency-light.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Package layout | Use `packages/weave/src/weave`, with package-local `tests` and `examples`. | The config package is movable as a future repository unit. |
| Distribution and import names | Distribution name `weave`; import package `weave`. | Direct config users hard-switch imports to `weave`. |
| Version metadata | Define package-local `weave.__version__`, initially aligned with the repository version while the packages share a release cadence. | Recipe manifests and package metadata no longer read `loom.__version__`. |
| Runtime dependencies | Move OmegaConf, Pydantic, and PyYAML requirements into `weave`; make root `loom` package metadata depend on `weave` for config adapter workflows, refreshing `uv.lock` or workspace metadata as applicable. | Loom installs the config frontend for supported authored-config workflows; future runtime-only install work remains out of scope. |
| Compatibility shim | Do not keep a final `loom.config` shim. | Existing pre-release import paths must change at once. |
| Helper ownership | Keep Loom runtime helpers in Loom; define config-owned equivalents for config artifacts in `weave`. | Avoids inverted dependency on config as a generic utility package. |
| Config errors | Define config-owned error roots in `weave.errors`; Loom adapters catch and translate them for CLI diagnostics. | `weave` remains independent from Loom's error hierarchy. |
| Recipe plugin entry point | Keep the existing `loom.recipes` entry-point group for Stage 23, but move recipe loading and catalog registration to `weave`. Do not add a second group in this stage. | Preserves recipe plugin metadata while making ownership explicit; revisit if a future standalone repo needs a renamed group. |
| Golden fixture timing | Add baseline golden fixtures before implementation movement; keep them authoritative after the port. | Artifact drift is caught during the hard switch. |
| Validation split | Introduce `make validate-weave`, `make test-weave`, `make test-weave-examples`, and `make build-weave`, then make final `make validate-pr` include the package evidence. | Reviewers can inspect independent config-package evidence and combined repository evidence. |
| Runtime sweep overrides | Replace `src/loom/pipeline/sweep/spec.py` imports from config override modules with Loom-owned duplicate validation or adapter-normalized plain data. | Sweep records remain runtime-owned. |

## Adapter Boundary Contract

Allowed Loom config adapter paths may import `weave`:

- `src/loom/cli/validate.py`
- `src/loom/cli/plan.py`
- `src/loom/cli/run.py`
- `src/loom/cli/sweep.py`
- `src/loom/diagnostics/preflight.py`, only when composing authored config for
  diagnostics
- `src/loom/queue/config.py`, only when loading or composing authored queue
  config
- `src/loom/plugins/diagnostics.py`, only when recipe diagnostics explicitly
  request loading; metadata-only recipe listing must not import config
  composition
- A small Loom-owned adapter helper module may be introduced if it centralizes
  config error translation or composition handoff without being imported by
  runtime internals.

Forbidden runtime import areas must not import `weave` composition
modules or config-package helper modules for functionality Loom owns:

- `src/loom/pipeline/**`, including `src/loom/pipeline/sweep/spec.py`
- `src/loom/pipeline/stores/**`
- `src/loom/authority/**`
- `src/loom/runs/**`
- `src/loom/records/**`
- `src/loom/serialization/**`
- `src/loom/provenance/**`
- `src/loom/io/**`
- Loom runtime plugin groups other than metadata-only recipe listing

Required boundary tests:

- `weave` imports no `loom`.
- `import loom`, `import loom.pipeline`, `import loom.serialization`,
  `import loom.plugins`, and core runtime package imports do not import
  `weave`.
- Allowed adapter modules can import and call `weave`.
- Runtime sweep specs preserve config-compatible override validation without
  importing config implementation modules.
- Metadata-only plugin listing can report recipe entry points without loading
  config composition.
- Plugin diagnostics with `load=True` delegates recipe catalog loading to
  `weave`; plugin diagnostics without loading remains metadata-only.

## Golden Fixture Strategy

Phase 1 seeds baseline fixtures from the current implementation before code
movement. Initial fixture inputs and outputs should live in root tests so they
can run against current `loom.config`:

- Inputs: `tests/fixtures/config/golden_project/`
- Expected outputs: `tests/golden/config/extraction-v23/`
- Baseline contract test:
  `tests/contracts/test_config_extraction_golden_artifacts_contract.py`

The expected output directory should include one stable JSON file per public
artifact family:

- `resolved-config.json`
- `redacted-config.json`
- `composition-manifest.json`
- `recipe-manifest.json`
- `source-artifact-records.json`
- `raw-source-snapshots.json`
- `config-fingerprint-record.json`
- `structured-config-errors.json`

When the package-local test tree exists, Phase 5 moves or mirrors the same
fixtures under:

- `packages/weave/tests/fixtures/golden_project/`
- `packages/weave/tests/golden/extraction-v23/`

Compatibility policy:

- Generated artifact output must match the baseline exactly after the
  implementation port unless a phase execution plan records an intentional
  break, rationale, migration note, and updated fixture review.
- The hard switch from `loom.config` to `weave` may change Python module
  names in error class identity, but structured user-facing error payloads
  should stay stable unless explicitly accepted.
- Golden tests should use public config APIs, not private implementation helper
  calls.

## Validation Command Strategy

The final stage state should expose these validation entrypoints:

| Command | Purpose | Owner |
| --- | --- | --- |
| `make test-weave` | Run package-local config unit, package, contract, and integration tests under `packages/weave/tests`. | `weave` |
| `make test-weave-examples` | Validate package-local config examples. | `weave` |
| `make build-weave` | Build the `weave` source and wheel distributions. | `weave` |
| `make validate-weave` | Run package-local lint, typecheck, tests, examples, and build. | `weave` |
| `make test-no-extra` | Run Loom default runtime tests. | Loom |
| `make test-config-extra` | Run Loom adapter workflows that require config dependencies through `weave`. | Loom |
| `make validate-pr` | Run the combined PR gate, including root Loom validation and `weave` validation by the final phase. | Repository |
| `make test-summary` | Write suite evidence for root Loom and `weave` results. | Repository |

Implementation may refine the exact Makefile wiring, but these target names and
suite responsibilities are the default contract for phase plans and PR bodies.

## Conflicts And Tradeoffs

- Clean separation creates duplicated helper behavior. This is accepted because
  Loom should not rely on `weave` as a generic utility library for
  runtime behavior.
- A hard switch is less migration-friendly than a compatibility shim. This is
  accepted for the pre-release stage and keeps the package boundary reviewable.
- Keeping the `loom.recipes` entry-point group is a naming compromise. It
  avoids broad plugin metadata churn while moving loading and catalog semantics
  to `weave`.
- Package-local validation adds Makefile and tooling complexity. This is
  accepted because independent package evidence is required before future
  repository extraction.
- Temporarily duplicating the config implementation during the port reduces
  cutover risk but must be removed by the hard-switch phase.

## Maintainability Assessment

The plan improves maintainability by making package ownership explicit and by
removing the current mixed responsibility where config artifacts depend on Loom
runtime helper modules. The main maintainability risk is helper drift between
Loom and `weave`; focused helper tests and golden artifact tests are
required mitigation. The plan also reduces future review complexity by keeping
package scaffold, implementation port, adapter cutover, test/example movement,
and docs hardening in separate phases.

## Extensibility Assessment

The package-local layout supports future standalone repository extraction, a
separate config release cadence, and config-specific examples without changing
Loom runtime internals. Adapter boundaries leave room for future Loom runtime
work to accept composed plain data without importing config composition. Recipe
plugins remain trusted and explicit; a future stage can rename the entry-point
group or support dual groups if standalone package users need that migration.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Duplicated plain-data, stable JSON, digest, fingerprint, override, and error helper behavior | Clean ownership is more important than a new shared-core package during extraction. | The duplicated behavior grows beyond small package-owned implementations, golden fixtures expose repeated drift, or future separate release cadence becomes painful. |
| Temporary duplicated config implementation during the port | Allows `weave` to be validated before deleting the in-tree implementation. | Phase 4 must remove `src/loom/config`; if it cannot, mark the phase blocked rather than keeping two implementations. |
| Hard switch with no import shim | User confirmed no `loom.config` shim by default. | Explicit future user instruction or a concrete packaging blocker that prevents Loom adapter paths from working. |
| Legacy `loom.recipes` entry-point group name remains | Preserves existing recipe plugin metadata while loader ownership moves to `weave`. | Future standalone `weave` repository needs a config-named group, or metadata-only Loom listing creates ambiguous duplicate loading. |
| Monorepo package validation wiring | Needed before package-local tests and examples can stand alone. | Validation becomes too slow or requires heavyweight tooling beyond current repo practices. |
| Public package-name availability for `weave` is not verified in this planning stage | Publishing is explicitly deferred and Stage 23 can validate local workspace packaging first. | A future publication phase finds a registry or ecosystem naming conflict, or isolated install checks resolve the wrong `weave` package. |

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `config-boundary-golden-fixtures` | merged | `codex/config-boundary-golden-fixtures` | [#200](https://github.com/samcantrill/loom/pull/200) | artifact baselines, import inventory | Pin config artifacts and boundary evidence before movement | targeted golden contract, package/import-boundary tests | none moved |
| 2 | `weave-package-scaffold` | merged | `codex/weave-package-scaffold` | [#201](https://github.com/samcantrill/loom/pull/201) | package metadata, config-owned helpers | Add installable package shell and duplicated config helper foundations | package import/build/helper tests, initial package validation target | package-local skeleton only |
| 3 | `weave-implementation-port` | merged | `codex/weave-implementation-port` | [#202](https://github.com/samcantrill/loom/pull/202) | `weave` implementation | Port config implementation into `weave` with package-owned dependencies | package-local config suites, golden parity | config examples may be smoke-copied only when needed |
| 4 | `weave-hard-switch-adapters` | merged | `codex/weave-hard-switch-adapters` | [#203](https://github.com/samcantrill/loom/pull/203) | Loom adapter rewiring, import cleanup | Hard-switch Loom to `weave` and remove `src/loom/config` | root package/contract/integration/e2e, import-boundary tests | runtime examples still in place |
| 5 | `config-tests-examples-validation` | merged | `codex/config-tests-examples-validation` | [#204](https://github.com/samcantrill/loom/pull/204) | test/example relocation, validation targets | Move config tests/examples beside the package and finalize validation commands | `make validate-weave`, targeted root adapter suites | package-local config examples |
| 6 | `config-extraction-docs-hardening` | merged | `codex/config-extraction-docs-hardening` | [#205](https://github.com/samcantrill/loom/pull/205) | docs, final validation, metadata | Align docs, structure, roadmap metadata, and final combined validation | `make validate-pr`, `make test-summary` | docs and example references verified |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Implementation-plan quality gate | workflow gate | Initial review, one refinement pass, and confirmation review completed. | resolved; passed on 2026-05-20 |

## Phase 1: Boundary And Golden Fixture Preparation

Status: merged
Slug: `config-boundary-golden-fixtures`
Branch: `codex/config-boundary-golden-fixtures`
Worktree: `/home/samcantrill/work/loom-worktrees/config-boundary-golden-fixtures`
PR: [#200](https://github.com/samcantrill/loom/pull/200)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: pin current config artifact behavior and current import-boundary facts
  before package movement begins.
- Files/modules owned:
  - `tests/fixtures/config/golden_project/`
  - `tests/golden/config/extraction-v23/`
  - `tests/contracts/test_config_extraction_golden_artifacts_contract.py`
  - `tests/package/test_import_boundaries.py`
  - targeted docs notes in this implementation plan only if execution evidence
    needs metadata updates
- Behavior implemented:
  - Baseline golden tests for resolved config, redacted config, composition
    manifests, recipe manifests, source artifact records, raw source snapshots,
    config fingerprint records, and structured config error payloads.
  - Import-boundary inventory that identifies current config imports and the
    intended allowed/disallowed boundary for later phases.
- Decisions applied:
  - Golden fixture timing from DAQ-5.
  - Helper ownership and adapter-boundary constraints from DAQ-3 and DAQ-4.
- Examples or docs covered: none beyond test fixture documentation.
- Out of scope:
  - Creating `packages/weave`.
  - Moving implementation modules.
  - Rewriting user import paths.
- Dependencies: current `loom.config` implementation and existing config tests.

### Tasks

- Add a compact, domain-neutral golden config fixture project.
- Add public-API golden tests that write or compare stable JSON expectations.
- Include a structured-error scenario that verifies user-facing error payload
  shape without coupling to private traceback details.
- Extend import-boundary tests with TODO or expected-current assertions that
  make the Phase 4 cutover target explicit.
- Record any artifact output that already differs from documented expectations
  as a blocker before implementation movement.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py` | Verify new golden artifact contract. | yes |
| `uv run pytest tests/package/test_import_boundaries.py` | Verify existing import boundaries still pass with new checks. | yes |
| `make test-contract` | Confirm contract suite health if golden coverage joins the contract tier. | yes |
| `make validate-pr` | Confirm the baseline fixtures did not destabilize the repo gate. | yes |

### Acceptance Evidence

- Behavior evidence: golden tests pass against the current implementation.
- Design-decision evidence: fixture scope maps to FR-6 and DAQ-5.
- Future-roadmap compatibility evidence: fixture files are package-movable and
  use public APIs.
- Interface, adapter, or protocol reuse evidence: no new runtime API is added.
- Documentation evidence: fixture intent is clear from test names and comments.
- Domain-neutrality evidence: fixtures use synthetic config values only.

### Phase Workflow State

- Phase execution plan: drafted and refined
- Planning/refinement budget: used; expanded-path draft and refine completed
- Implementation/refinement budget: used for manager-local validation fixes
- PR review budget: consumed by manager pre-submit review; no blocking findings
- Blocker-resolution budget: 1/3 used for CI-only path portability fix
- Pre-submit blocker gate: passed
- Merge record: merged into `develop` via PR #200

### Risks And Stop Conditions

- Risks: fixture expectations may reveal undocumented current artifact drift.
- Stop conditions: golden output cannot be made deterministic through public
  APIs, or fixture output requires private implementation hooks.
- Assumptions: existing config tests already cover semantic behavior; this
  phase adds artifact-shape pinning rather than broad semantic coverage.

### Completion Summary

- Implementation: added root golden config fixtures, eight checked-in
  extraction baseline JSON files, a public-API golden contract, and
  current-state config import-boundary assertions without moving runtime code.
- Validation: targeted golden contract passed; package import-boundary tests
  passed; `make test-contract`, `make validate-pr`, `make test-config-extra`,
  and `make test-summary` passed locally. GitHub CI `checks` passed on
  2026-05-20 after fixing the structured-error message path portability issue.
- PR: [#200](https://github.com/samcantrill/loom/pull/200), target
  `develop`, head `codex/config-boundary-golden-fixtures`.
- Merge: squash-merged on 2026-05-20 with merge commit
  `c185731c316f7394ea7873a44c6395e2becf18a0`; remote phase branch deleted by
  merge command, local branch/worktree cleanup pending after metadata update.
- Follow-up: Phase 5 should move or mirror the root-owned golden fixtures under
  package-local `weave` tests; Phase 4 should flip the current-state import
  inventory to final `weave` boundary enforcement.

## Phase 2: Package Scaffold And Config Helper Foundations

Status: merged
Slug: `weave-package-scaffold`
Branch: `codex/weave-package-scaffold`
Worktree: `/home/samcantrill/work/loom-worktrees/weave-package-scaffold`
PR: [#201](https://github.com/samcantrill/loom/pull/201)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: add an independently importable `weave` package shell and the
  config-owned helper foundations needed before implementation porting.
- Files/modules owned:
  - `packages/weave/pyproject.toml`
  - `packages/weave/src/weave/__init__.py`
  - `packages/weave/src/weave/py.typed`
  - `packages/weave/src/weave/plain.py` or equivalent
  - `packages/weave/src/weave/json.py` or equivalent
  - `packages/weave/src/weave/digests.py` or equivalent
  - `packages/weave/src/weave/errors.py`
  - `packages/weave/tests/`
  - Makefile and tool configuration needed for package-local validation
- Behavior implemented:
  - `import weave` succeeds without importing `loom`.
  - Config-owned helper modules support the subset of plain-data, stable JSON,
    digest, fingerprint alias, and error behavior needed by config records.
  - Package-local version metadata exists.
- Decisions applied:
  - DAQ-1 package layout.
  - DAQ-3 duplicated helper ownership.
  - DAQ-7 validation command split.
  - DAQ-9 config-owned errors.
- Examples or docs covered: package-local examples directory skeleton if useful,
  but no authoring example migration yet.
- Out of scope:
  - Porting config composition implementation.
  - Updating Loom adapter paths.
  - Removing `src/loom/config`.
- Dependencies: Phase 1 golden fixtures.

### Tasks

- Add package metadata with distribution and import package name `weave`,
  Python support aligned with Loom, and config runtime dependencies.
- Add package-local `py.typed` and version metadata.
- Add config-owned helper modules with focused tests.
- Add import-boundary tests proving `weave` imports no `loom`.
- Add Make targets for `test-weave`, `build-weave`, and an initial
  `validate-weave`.
- Keep root Loom behavior unchanged.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `make test-weave` | Run package-local helper and import tests. | yes |
| `make build-weave` | Build the new package. | yes |
| `make validate-weave` | Prove the initial package-local gate. | yes |
| `uv run pytest tests/package/test_import_boundaries.py` | Prove root import boundaries remain stable. | yes |
| `make validate-pr` | Prove the repository gate still passes. | yes |

### Acceptance Evidence

- Behavior evidence: `weave` imports cleanly and helper tests pass.
- Design-decision evidence: helper behavior is package-owned and does not
  import Loom.
- Future-roadmap compatibility evidence: package files are under a movable
  package directory.
- Interface, adapter, or protocol reuse evidence: helper APIs are config-owned
  and do not become Loom runtime dependencies.
- Documentation evidence: package metadata and target names describe ownership.
- Domain-neutrality evidence: helper tests use neutral synthetic values.

### Phase Workflow State

- Phase execution plan: drafted and refined
- Planning/refinement budget: used; expanded-path draft and refine completed
- Implementation/refinement budget: unused
- PR review budget: consumed by `loom_phase_reviewer`; one package dependency
  metadata blocker resolved before merge
- Blocker-resolution budget: 2/3 used for mapping-proxy helper contract and
  config runtime dependency metadata fixes
- Pre-submit blocker gate: passed
- Merge record: merged into `develop` via PR #201

### Risks And Stop Conditions

- Risks: monorepo package tooling may need root configuration changes.
- Stop conditions: package build or typecheck requires heavyweight tooling not
  justified by the stage.
- Assumptions: config dependency versions remain the existing optional config
  dependency families unless implementation evidence requires tighter bounds.

### Completion Summary

- Implementation: added `packages/weave` with package metadata, normal config
  runtime dependencies, `py.typed`, version metadata, package-local README,
  config-owned helpers for plain data, stable JSON, digests, and structured
  config errors, package-local helper tests, initial `test-weave`,
  `build-weave`, and `validate-weave` targets, and root import-boundary tests
  proving `weave` does not import Loom and Loom core imports do not import
  `weave`.
- Validation: `make test-weave`, `make build-weave`, `make validate-weave`,
  `uv run pytest tests/package/test_import_boundaries.py`,
  `make validate-pr`, and `make test-summary` passed locally. GitHub CI
  `checks` passed on 2026-05-20 for the current PR head after a no-op branch
  update was pushed to attach CI to the final validated tree.
- Review: `loom_phase_reviewer` found one blocking dependency metadata issue;
  it was resolved by moving OmegaConf, Pydantic, and PyYAML into normal
  `weave` runtime dependencies and adding package-local metadata regression
  coverage.
- PR: [#201](https://github.com/samcantrill/loom/pull/201), target
  `develop`, head `codex/weave-package-scaffold`.
- Merge: squash-merged on 2026-05-20 with merge commit
  `a2e7baafcb9dfe994587b79425ef80e4d9134eab`; remote phase branch cleanup
  pending after metadata update because the local branch was checked out in its
  worktree during merge.
- Follow-up: Phase 3 should branch from updated `develop` and port the config
  implementation into `weave` without adding a `loom.config` shim or changing
  adapter paths early.

## Phase 3: Config Implementation Port To `weave`

Status: merged
Slug: `weave-implementation-port`
Branch: `codex/weave-implementation-port`
Worktree: `/home/samcantrill/work/loom-worktrees/weave-implementation-port`
PR: [#202](https://github.com/samcantrill/loom/pull/202)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: port the config implementation into `weave` using config-owned
  helper modules and package-owned dependencies, while preserving current
  artifact behavior.
- Files/modules owned:
  - `packages/weave/src/weave/**`
  - `packages/weave/tests/**`
  - `tests/golden/config/extraction-v23/**`
  - targeted package/build/tooling config
- Behavior implemented:
  - Public config APIs are available through `weave`.
  - Config implementation imports package-owned helpers and package-owned
    errors, not Loom runtime helper modules.
  - Recipe catalogs, target instantiation, redaction, provenance, manifests,
    source artifacts, raw source snapshots, and config fingerprints work under
    `weave`.
  - Golden config artifacts match the Phase 1 baseline.
- Decisions applied:
  - FR-2 config implementation namespace move.
  - FR-3 helper ownership split.
  - FR-6 golden artifact compatibility.
  - DAQ-6 recipe plugin ownership, with loading moved into `weave` while
    keeping the `loom.recipes` entry-point group.
- Examples or docs covered: only minimal package API examples if needed for
  package-local smoke tests.
- Out of scope:
  - Removing `src/loom/config`.
  - Rewiring Loom adapter paths.
  - Moving all user-facing examples.
- Dependencies: Phases 1 and 2.

### Tasks

- Port config modules from `src/loom/config` into `packages/weave`.
- Rewrite package-internal imports from `loom.config` to `weave`.
- Replace `loom.serialization`, Loom digest/fingerprint helpers, Loom error
  roots, and `loom.__version__` with package-owned equivalents.
- Move or duplicate enough tests into `packages/weave/tests` to prove the
  new package behavior before the root hard switch.
- Keep the old in-tree implementation only as a temporary baseline for root
  Loom until Phase 4 removes it.
- Assert `weave` imports no `loom` after the port.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `make validate-weave` | Prove package-local implementation health. | yes |
| `uv run pytest packages/weave/tests` | Run the package-local suite directly when useful for debugging. | yes |
| `uv run pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py` | Prove baseline artifacts still match. | yes |
| `uv run pytest tests/package/test_import_boundaries.py` | Prove `weave` has no Loom imports. | yes |
| `make validate-pr` | Prove root behavior still passes with the old implementation in place. | yes |

### Acceptance Evidence

- Behavior evidence: `weave` package APIs pass moved config tests.
- Design-decision evidence: package implementation uses package-owned helpers.
- Future-roadmap compatibility evidence: implementation is under movable
  package-local paths.
- Interface, adapter, or protocol reuse evidence: package public API mirrors the
  confirmed config surface under `weave`.
- Documentation evidence: package metadata and test names make the temporary
  duplicate implementation explicit.
- Domain-neutrality evidence: no domain-specific recipes or schemas are added.

### Phase Workflow State

- Phase execution plan:
  `docs/roadmap/stage-23/phases/weave-implementation-port.md`
- Planning/refinement budget: used by `loom_phase_planner` draft and refine
  passes.
- Implementation/refinement budget: no `loom_phase_refiner` pass used; manager
  performed one scoped takeover/refinement after the implementation agent
  stalled.
- PR review budget: used by `loom_phase_reviewer`; one blocking hierarchy
  parity finding was resolved before merge.
- Blocker-resolution budget: 2/3 used for manager takeover/package-boundary
  fixes and the PR-review error hierarchy parity fix; no remaining blockers.
- Pre-submit blocker gate: passed locally and in GitHub CI.
- Merge record: merged into `develop` via PR #202.

### Risks And Stop Conditions

- Risks: copying implementation before deleting the old path can hide drift if
  package-local tests are incomplete.
- Stop conditions: `weave` cannot preserve golden artifacts without
  importing Loom, or package-owned helper behavior becomes too broad for this
  stage.
- Assumptions: temporary duplicate implementation is removed in Phase 4 and is
  not treated as final compatibility support.

### Completion Summary

- Implementation: ported config composition, loading, includes, overrides,
  provenance, artifact records, fingerprints, recipes, instantiation, target
  checks, and structured config errors into `packages/weave/src/weave` using
  package-owned helpers and dependencies. Root Loom still uses
  `src/loom/config` until Phase 4.
- Validation: `make test-weave`, `make validate-weave`,
  `PYTHONPATH=packages/weave/src uv run --extra config pytest packages/weave/tests`,
  import-boundary tests, golden config extraction contract tests, focused
  config contracts, `make validate-pr`, and `make test-summary` passed locally.
  GitHub CI `checks` passed on 2026-05-20 for head
  `8de4a7c13908f7b60072a50493684156f2c70571`.
- Review: `loom_phase_reviewer` found one blocking structured-error hierarchy
  drift; it was fixed by restoring `ConfigIncludeResolutionError` and
  `DuplicateRecipeError` inheritance parity with the trusted `loom.config`
  baseline and adding package regression coverage.
- PR: [#202](https://github.com/samcantrill/loom/pull/202), target
  `develop`, head `codex/weave-implementation-port`.
- Merge: squash-merged on 2026-05-20 with merge commit
  `51adb08f9761bf35cf5b73df576c2c1b496d0120`.
- Follow-up: Phase 4 should branch from updated `develop` and hard-switch Loom
  adapter paths to `weave`, remove `src/loom/config`, and enforce the final
  import boundaries.

## Phase 4: Hard Switch Loom Adapters And Import Boundaries

Status: merged
Slug: `weave-hard-switch-adapters`
Branch: `codex/weave-hard-switch-adapters`
Worktree: `/home/samcantrill/work/loom-worktrees/weave-hard-switch-adapters`
Worktree cleanup: removed after merge
PR: [#203](https://github.com/samcantrill/loom/pull/203), target
  `develop`, head `codex/weave-hard-switch-adapters`.
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: make Loom consume authored config through `weave`, remove
  `src/loom/config`, and enforce runtime import boundaries.
- Files/modules owned:
  - `src/loom/cli/validate.py`
  - `src/loom/cli/plan.py`
  - `src/loom/cli/run.py`
  - `src/loom/cli/sweep.py`
  - `src/loom/diagnostics/preflight.py`
  - `src/loom/queue/config.py`
  - `src/loom/pipeline/sweep/spec.py`
  - `src/loom/plugins/recipes.py`
  - `src/loom/plugins/diagnostics.py`
  - root `pyproject.toml`
  - `uv.lock` and workspace metadata as applicable
  - `tests/package/test_import_boundaries.py`
  - root config adapter tests under `tests/contracts`, `tests/integration`,
    and `tests/e2e`
  - removal of `src/loom/config/**`
- Behavior implemented:
  - Loom CLI/API config workflows call `weave`.
  - Loom adapters catch config-owned errors and translate them into existing
    CLI diagnostics and exit categories.
  - Runtime sweep specs no longer import config override modules.
  - Runtime internals do not import `weave` except through approved
    adapter paths.
  - Root package metadata installs `weave` for Loom config adapter
    workflows, and a built/isolated package smoke proves `loom` can import
    `weave`.
  - `src/loom/config` is gone and no final `loom.config` shim exists.
- Decisions applied:
  - FR-4 Loom adapter rewiring.
  - DAQ-2 no shim.
  - DAQ-4 adapter boundary.
  - DAQ-8 runtime sweep override ownership.
  - DAQ-9 error translation.
- Examples or docs covered: only imports needed to keep existing root examples
  passing; full example relocation is Phase 5.
- Out of scope:
  - Moving all config tests/examples.
  - Broad docs rewrite.
  - New config semantics.
- Dependencies: Phase 3.

### Tasks

- Replace Loom adapter imports from `loom.config` with `weave`.
- Delete `src/loom/config` after all root imports are rewired.
- Implement Loom-owned duplicate sweep override validation or adapter-normalized
  plain-data handling for `src/loom/pipeline/sweep/spec.py`.
- Update config error handling in CLI and adapter paths.
- Split recipe plugin behavior so `weave` loads recipe catalogs and Loom
  keeps only metadata listing where needed.
- Update `src/loom/plugins/diagnostics.py` so recipe diagnostics with
  `load=True` delegates recipe loading to `weave`, while metadata-only
  listing does not import config composition.
- Update root package dependency metadata so `loom` depends on `weave`
  for config adapter workflows, refresh `uv.lock` or workspace metadata as
  applicable, and remove or reshape the old root `config` extra once its
  dependencies are owned by `weave`.
- Update import-boundary tests to forbid accidental runtime imports of
  `weave`.
- Update root tests that intentionally referenced `loom.config` to the new
  adapter or package surfaces.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `make validate-weave` | Prove config package still passes after root cutover. | yes |
| `uv lock --check` or refreshed `uv.lock` review | Prove root dependency/workspace metadata is coherent after making `loom` depend on `weave`. | yes |
| `uv build` | Prove root `loom` packaging still builds with the new dependency metadata. | yes |
| isolated installed-package import and CLI smoke | Prove the built or isolated root package can import `loom` and `weave` and run a minimal config-facing CLI path. | yes |
| `uv run pytest tests/package/test_import_boundaries.py` | Prove hard-switch import boundaries. | yes |
| `make test-package` | Prove root package/API behavior after removing `src/loom/config`. | yes |
| `make test-contract` | Prove contracts affected by CLI, plugins, sweeps, and config artifacts. | yes |
| `make test-integration` | Prove config-consuming Loom workflows. | yes |
| `make test-e2e` | Prove representative CLI hard-switch workflows. | yes |
| `make validate-pr` | Prove combined root gate. | yes |

### Acceptance Evidence

- Behavior evidence: root config adapter tests pass through `weave`.
- Design-decision evidence: no final `loom.config` shim exists.
- Future-roadmap compatibility evidence: runtime internals are isolated from
  config composition.
- Interface, adapter, or protocol reuse evidence: adapter paths are explicit and
  plain-data handoff remains intact.
- Documentation evidence: tests and phase notes record allowed adapter modules.
- Domain-neutrality evidence: no runtime domain behavior changes are added.

### Phase Workflow State

- Phase execution plan: drafted and refined in
  `docs/roadmap/stage-23/phases/weave-hard-switch-adapters.md`
- Planning/refinement budget: used; expanded-path draft and refine completed
- Implementation/refinement budget: not used; manager completed the phase after
  the assigned executor was unavailable
- PR review budget: used; manager automated review found no blocking issues
- Blocker-resolution budget: 1/3 used for manager takeover and focused
  validation fixes after the executor stopped before implementation
- Pre-submit blocker gate: passed
- Merge record: squash-merged on 2026-05-20 with merge commit
  `44d85faef8a6b40aec2ed08f998a57b9ad489cd8`

### Risks And Stop Conditions

- Risks: this is the highest-risk cutover because it removes the old import path
  and touches CLI, queue, diagnostics, sweeps, and plugins.
- Stop conditions: root Loom requires broad runtime imports from `weave`,
  config errors cannot preserve diagnostics through adapter translation, or
  `src/loom/config` cannot be removed without keeping a shim.
- Assumptions: `loom` may depend on `weave` as a normal package
  dependency for this stage.

### Completion Summary

- Implementation: hard-switched Loom CLI, diagnostics, queue, sweep, and plugin
  diagnostics adapter paths to `weave`; removed `src/loom/config` with no shim;
  replaced runtime sweep override validation with Loom-owned path validation;
  updated root package metadata and lock data to resolve the local
  `packages/weave` project; updated focused tests, examples, and import
  boundaries.
- Validation: `make validate-weave`, installed wheel smoke, targeted adapter
  checks, `make test-package`, `make test-contract`, `make test-integration`,
  `make test-e2e`, `make test-config-extra`, `make validate-pr`, and
  `make test-summary` passed. GitHub CI `checks` completed successfully on
  2026-05-20 before merge.
- PR: [#203](https://github.com/samcantrill/loom/pull/203), target
  `develop`, head `codex/weave-hard-switch-adapters`.
- Merge: squash-merged on 2026-05-20 with merge commit
  `44d85faef8a6b40aec2ed08f998a57b9ad489cd8`.
- Cleanup: remote branch, stale tracking ref, local branch, and worktree were
  removed after merge.
- Follow-up: Phase 5 should branch from updated `develop` and relocate
  config-owned tests, examples, and validation evidence into `packages/weave`
  without reintroducing `loom.config`.

## Phase 5: Test, Example, And Validation Relocation

Status: merged
Slug: `config-tests-examples-validation`
Branch: `codex/config-tests-examples-validation`
Worktree: `/home/samcantrill/work/loom-worktrees/config-tests-examples-validation`
Worktree cleanup: removed after merge
PR: [#204](https://github.com/samcantrill/loom/pull/204), target
  `develop`, head `codex/config-tests-examples-validation`.
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: make tests, examples, and validation reflect the final ownership split.
- Files/modules owned:
  - `packages/weave/tests/**`
  - `packages/weave/examples/**`
  - root `tests/**` for remaining Loom runtime adapter coverage
  - `examples/**` for remaining Loom runtime examples
  - `make/test/*.mk`
  - `make/dev/*.mk`
  - `tools/test_harness*` if summary/report support needs package suite
    awareness
- Behavior implemented:
  - Config-owned tests live under `packages/weave/tests`.
  - Config-owned examples live under `packages/weave/examples`.
  - Loom runtime tests and examples remain under root paths.
  - Package-local validation and example checks are wired into documented
    targets.
  - `make test-summary` can report package-local config evidence.
- Decisions applied:
  - FR-5 test and example relocation.
  - DAQ-7 validation command split.
  - DAQ-10 docs/structure update boundary, for validation references only.
- Examples or docs covered:
  - Config composition examples.
  - Includes and overlays examples.
  - Recipe examples.
  - Target instantiation examples.
  - Artifact safety and fingerprint examples.
  - Structured error examples.
- Out of scope:
  - Broad feature-doc rewrites.
  - New examples beyond relocation or minimal ownership clarification.
  - Runtime behavior changes.
- Dependencies: Phase 4.

### Tasks

- Move config test files from root `tests` into package-local test tiers.
- Keep or add root tests only where Loom adapter behavior is the subject.
- Move config authoring examples out of root `examples/authoring` and into
  `packages/weave/examples`.
- Update example imports from `loom.config` to `weave`.
- Add package-local example validation.
- Wire summary output so PR bodies can report `weave` suites separately.
- Keep root runtime examples focused on pipeline execution, stores, queues,
  operations, cleanup, containers, SLURM, sweeps, plugins, and runtime CLI
  workflows.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `make test-weave` | Prove relocated package tests. | yes |
| `make test-weave-examples` | Prove relocated config examples. | yes |
| `make validate-weave` | Prove independent config package validation. | yes |
| `make test-config-extra` | Prove root config adapter workflows. | yes |
| `make test-summary` | Prove suite evidence includes package and root results. | yes |
| `make validate-pr` | Prove combined repository validation. | yes |

### Acceptance Evidence

- Behavior evidence: package-local tests and examples pass.
- Design-decision evidence: test/example ownership matches package ownership.
- Future-roadmap compatibility evidence: package tests/examples are movable as a
  unit.
- Interface, adapter, or protocol reuse evidence: root tests cover adapter
  boundaries rather than config internals.
- Documentation evidence: validation target names are stable for PR evidence.
- Domain-neutrality evidence: examples remain synthetic and package-appropriate.

### Phase Workflow State

- Phase execution plan: drafted and refined in
  `docs/roadmap/stage-23/phases/config-tests-examples-validation.md`
- Planning/refinement budget: used; expanded-path draft and refine completed
- Implementation/refinement budget: not used; targeted validation passed after
  manager implementation
- PR review budget: used; manager automated review found no blocking issues
- Blocker-resolution budget: 0/3 used
- Pre-submit blocker gate: passed
- Merge record: squash-merged on 2026-05-20 with merge commit
  `b165938d889e0bb46169afed711704c5fc30e96d`

### Risks And Stop Conditions

- Risks: moving tests can accidentally reduce root adapter coverage or duplicate
  package semantics in the wrong suite.
- Stop conditions: package-local examples need Loom runtime modules, or summary
  tooling cannot represent package evidence without broad harness redesign.
- Assumptions: root runtime examples may still call `weave` only as a
  frontend input when demonstrating Loom workflows.

### Completion Summary

- Implementation: moved config-owned unit, contract, and pure composition
  integration tests into `packages/weave/tests`; moved config authoring examples
  into `packages/weave/examples`; added package-local support fixtures, example
  execution and manifest validation, pytest configuration, `test-weave-examples`,
  expanded `validate-weave`, and `weave` / `weave-examples` test-summary rows.
- Validation: `make test-weave` passed with 375 tests; `make
  test-weave-examples` passed with 8 checks; `make validate-weave` passed;
  focused root config adapter tests passed outside the sandbox with 26 tests;
  `make validate-pr` passed outside the sandbox; `make test-summary` passed with
  package, unit, contract, integration, e2e, config-extra, weave, and
  weave-examples rows. GitHub CI `checks` completed successfully on 2026-05-20
  before merge.
- PR: [#204](https://github.com/samcantrill/loom/pull/204), target
  `develop`, head `codex/config-tests-examples-validation`.
- Merge: squash-merged on 2026-05-20 with merge commit
  `b165938d889e0bb46169afed711704c5fc30e96d`.
- Cleanup: remote branch, stale tracking ref, local branch, and worktree were
  removed after merge.
- Follow-up: Phase 6 should update user-facing docs and historical example
  coverage references to describe `weave` as the config authoring package and
  verify final combined validation.

## Phase 6: Documentation And Final Hardening

Status: merged
Slug: `config-extraction-docs-hardening`
Branch: `codex/config-extraction-docs-hardening`
Worktree: `/home/samcantrill/work/loom-worktrees/config-extraction-docs-hardening`
Worktree cleanup: removed after merge
PR: [#205](https://github.com/samcantrill/loom/pull/205), target
  `develop`, head `codex/config-extraction-docs-hardening`.
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: make repository docs, architecture maps, roadmap metadata, and final
  validation evidence match the completed package split.
- Files/modules owned:
  - `docs/structure.md`
  - `docs/loom.md`
  - `docs/features/config.md`
  - `docs/features/serialization.md`
  - `docs/features/fingerprints.md`
  - `docs/features/errors.md`
  - `docs/features/plugins.md`
  - `docs/features/testing.md`
  - `docs/features/cli.md`
  - `docs/features/config-test-matrix.md`
  - `docs/roadmap.md`
  - this implementation plan completion metadata
  - README and example catalog references when affected
- Behavior implemented:
  - Docs describe `weave` as the config authoring distribution and import
    package.
  - Docs describe Loom as the workflow/runtime package with explicit config
    adapter edges.
  - Import examples and module coverage no longer present `loom.config` as the
    public config path.
  - Final validation runs and suite evidence are recorded.
- Decisions applied:
  - DAQ-10 docs/structure update boundary.
  - All accepted risks and revisit triggers from design-safety review.
- Examples or docs covered: all user-facing docs that reference config import
  paths, package boundaries, plugin recipe ownership, config errors,
  serialization/fingerprint ownership, CLI behavior, and validation tiers.
- Out of scope:
  - New config semantics.
  - Additional package splits.
  - Publishing or release automation.
- Dependencies: Phase 5.

### Tasks

- Update source-tree and package-boundary docs.
- Update config feature docs from `loom.config` to `weave` where the
  public config package is meant.
- Update serialization, fingerprint, and error docs to explain duplicated
  package-owned helper behavior.
- Update plugin docs to record that recipe loading is config-owned while the
  `loom.recipes` entry-point group remains the Stage 23 compatibility group.
- Update CLI docs to describe adapter behavior and error translation.
- Update testing docs and config test matrix with package-local and combined
  validation commands.
- Update roadmap metadata and this implementation plan with final completion
  evidence.
- Run final validation and summarize suite-level evidence for PR preparation.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `make validate-weave` | Prove standalone package remains healthy. | yes |
| `make validate-pr` | Prove final combined PR gate. | yes |
| `make test-summary` | Produce suite evidence for final PR body. | yes |
| targeted docs/example checks added by Phase 5 | Prove import examples and example catalogs are current. | yes |
| `rg "loom\\.config" docs examples tests src packages` review | Confirm remaining legacy references are intentional historical notes only. | yes |

### Acceptance Evidence

- Behavior evidence: final validation passes with package and root suites.
- Design-decision evidence: docs match confirmed package ownership decisions.
- Future-roadmap compatibility evidence: docs and package layout are ready for a
  future repository split.
- Interface, adapter, or protocol reuse evidence: adapter boundaries and plugin
  ownership are documented.
- Documentation evidence: feature docs, structure docs, roadmap, and examples
  agree on `weave`.
- Domain-neutrality evidence: docs do not add domain-specific config examples.

### Phase Workflow State

- Phase execution plan: drafted and refined in
  `docs/roadmap/stage-23/phases/config-extraction-docs-hardening.md`
- Planning/refinement budget: used; expanded-path draft and refine completed
- Implementation/refinement budget: not needed; targeted and full validation
  passed after manager implementation
- PR review budget: used; manager automated review found no blocking issues
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed locally
- Merge record: squash-merged into `develop` via PR #205 with merge commit
  `d218eecb95e94e9846fd98beba9991fb9ab2342e`

### Risks And Stop Conditions

- Risks: stale `loom.config` references may remain as accidental instructions
  rather than historical notes.
- Stop conditions: final `make validate-pr` cannot run, final docs contradict
  package ownership, or package-local validation evidence cannot be summarized.
- Assumptions: broad prose cleanup stays limited to the package split and does
  not reopen feature semantics.

### Completion Summary

- Implementation: updated current user-facing docs, README examples,
  source-tree structure docs, config/serialization/fingerprint/error/plugin/CLI
  feature docs, package docs, example coverage references, testing docs,
  roadmap metadata, and a narrow docs/example test expectation so repository
  instructions now present `weave` as the config authoring package and Loom as
  the runtime consuming authored config through explicit adapter paths.
- Validation: `make validate-weave` passed; targeted docs/example tests passed
  outside the sandbox with 33 tests; active import-reference sweeps found no
  current `loom.config` instructions beyond intentional absence assertions;
  `make validate-pr` passed outside the sandbox; `make test-summary` passed
  with package, unit, contract, integration, e2e, config-extra, weave, and
  weave-examples rows.
- PR: [#205](https://github.com/samcantrill/loom/pull/205), target
  `develop`, head `codex/config-extraction-docs-hardening`.
- Review: manager automated review verified PR target, scope, whitespace,
  current-doc import sweeps, and GitHub CI. No blocking findings remained.
- Merge: squash-merged on 2026-05-20 with merge commit
  `d218eecb95e94e9846fd98beba9991fb9ab2342e`; GitHub CI `checks`
  completed successfully on 2026-05-20 before merge.
- Cleanup: remote branch, stale tracking ref, local branch, and worktree were
  removed after merge.
- Follow-up: future standalone `weave` publication should revisit the
  `loom.recipes` entry-point group name and registry naming availability.

## Cross-Phase Validation

- Full relevant test command: `make validate-pr`
- Suite evidence command: `make test-summary`
- Package-local config gate: `make validate-weave`
- Package-local config examples: `make test-weave-examples`
- Docs/template checks: docs import-reference scans, example catalog checks, and
  feature-doc validation added or updated by Phase 5.
- Domain-neutrality checks: examples and fixtures use synthetic values and do
  not introduce domain recipes, schemas, or stages.
- Import-boundary checks:
  - `weave` imports no `loom`.
  - core Loom runtime imports do not import `weave`.
  - approved Loom adapter paths can import `weave`.
  - `src/loom/config` does not exist after Phase 4.
- Packaging checks:
  - root `loom` package metadata depends on `weave` after the hard switch.
  - lock/workspace metadata is current.
  - root and `weave` builds pass.
  - an isolated installed-package smoke can import `loom` and `weave`.
- Manual review focus:
  - Golden fixture diffs and any explicit accepted break.
  - Config error translation through CLI/adapters.
  - Recipe plugin ownership and entry-point group handling.
  - Plugin diagnostics behavior for metadata-only listing versus `load=True`.
  - Root versus package-local test ownership.
  - Remaining `loom.config` references.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Root dependency/package metadata ownership was missing | blocker | Added root `pyproject.toml`, `uv.lock`/workspace metadata, root build, lock, and isolated import/CLI smoke obligations to Phase 4 and cross-phase validation. | resolved; confirmation review passed |
| Plugin diagnostics boundary was omitted | blocker | Added `src/loom/plugins/diagnostics.py` to allowed adapter paths and Phase 4 ownership; recorded metadata-only versus `load=True` recipe diagnostics behavior and required tests. | resolved; confirmation review passed |

Gate result:

- Status: passed on 2026-05-20
- Review evidence:
  - Initial `loom_plan_reviewer` quality-gate review completed on 2026-05-20;
    gate blocked on two plan omissions: root dependency/package metadata
    ownership and plugin diagnostics boundary coverage.
  - Refinement pass completed on 2026-05-20 by updating Phase 4 ownership,
    adapter-boundary contract, validation obligations, cross-phase packaging
    checks, and this review table.
  - Confirmation review by `loom_plan_reviewer` completed on 2026-05-20 and
    found no blocking findings. It confirmed both initial blockers were
    resolved and no new blocker was introduced.
  - User-directed naming update completed after the confirmation review on
    2026-05-20, replacing the previous config package/distribution/import names
    with `weave` while keeping the approved design and phase structure intact.
- Accepted risks:
  - Hard switch with no `loom.config` shim.
  - Duplicated package-owned helper behavior.
  - Short-lived duplicated config implementation during port.
  - Config-owned errors translated by Loom adapters rather than shared
    inheritance.
  - Existing `loom.recipes` entry-point group retained while recipe loading
    moves to `weave`.
- Revisit triggers:
  - Duplicated helper behavior becomes too broad or repeatedly drifts.
  - Future standalone `weave` repository needs a renamed plugin group or
    independent release cadence.
  - Future publication or isolated install work discovers a `weave` package-name
    conflict.
  - CLI/API consumers cannot preserve structured config diagnostics through
    adapter translation.
  - Monorepo package validation needs heavyweight tooling or slows the default
    gate beyond PR suitability.

## Final Approval

- Approval status: approved for Phase 1 execution planning
- Approved scope: six-phase Stage 23 standalone config package extraction plan,
  with Phase 1 beginning at boundary and golden fixture preparation
- Accepted risks:
  - Hard switch with no `loom.config` shim.
  - Duplicated package-owned helper behavior.
  - Short-lived duplicated config implementation during port.
  - Config-owned errors translated by Loom adapters rather than shared
    inheritance.
  - Existing `loom.recipes` entry-point group retained while recipe loading
    moves to `weave`.
  - Root `loom` package depends on `weave` for config adapter workflows;
    runtime-only install work remains deferred.
  - Public package-name availability for `weave` is not verified until a future
    publication-oriented step.
- Deferred items:
  - Separate repository publication.
  - `loom.config` compatibility shim.
  - Hydra compatibility or new config language features.
  - Untrusted-config sandboxing.
  - Runtime-only Loom install without config adapter dependencies.
