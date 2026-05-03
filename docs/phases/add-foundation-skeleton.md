# Phase 1 Expanded Plan: Foundation

## Metadata

- Status: merged locally into `develop` after manager review.
- Branch: `codex/add-foundation-skeleton`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-foundation-skeleton`.
- Expanded plan path: `docs/phases/add-foundation-skeleton.md`.
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`.
- Source phase: `Phase 1 - Foundation`.
- Base branch: local `develop` at `4878e95eda64c3d8d969fcfcc658d6b082a7f310`.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers recorded in the full plan.
- Setup limitation: `git fetch origin` was unavailable. The sandboxed fetch could not write `.git/FETCH_HEAD`, and the escalated fetch reached GitHub but failed with SSH public-key authentication. Per the planning prompt, this worktree was created from the local `develop` branch.
- Blockers: none.

## Objective

Create the foundation skeleton for `loom` v0 without implementing runtime behavior: import-safe package boundaries, simple shared ID aliases, broad catchable errors, UTC timestamp helpers, unsupported stubs for explicitly deferred public callables, and tests that guard the import surface.

The phase should leave later subsystem phases free to add real records, provenance, serialization, I/O, config, pipeline, store, executor, and CLI behavior behind stable import paths.

## Full-Plan Context

The v0 plan keeps `loom` source-tree first, domain-neutral, and typed. The current package is metadata-only, so this phase establishes the package shape before primitives, serialization, config, pipeline planning, stores, and execution are added.

Key controlling constraints:

- Preserve the source-tree layout and dependency direction in `docs/structure.md`.
- Keep `loom.__init__` cheap and safe to import; it must not import config composition, pipeline runners, CLI modules, plugin discovery, optional backends, or downstream project packages.
- Keep runtime dependencies empty in this phase.
- Treat authored configs as trusted project code, but do not implement config behavior yet.
- Keep deferred functionality import-safe and explicit when called.
- Keep Phase 1 limited to structure, broad shared helpers, and tests.
- Where feature documents describe broader future behavior, the canonical
  implementation plan controls this phase.

## Source Phase Summary

From `docs/implementation-plans/implementation-plan-v0.md`, Phase 1 was
`Status: pending` with branch `codex/add-foundation-skeleton` at plan
expansion time. PR preparation updated the canonical phase status to `pr_open`;
local manager review and squash merge later updated it to `merged`.

Goal:

- Create the package skeleton, public import surface, shared errors, timestamp/id helpers, and import-boundary guardrails without implementing runtime behavior.

Required checkpoints:

- Add `loom.ids`, `loom.errors`, and `loom.timestamps`.
- Add import-safe package skeletons for `records`, `provenance`, `serialization`, `io`, `config`, `pipeline`, `pipeline.graph`, `pipeline.planning`, `pipeline.execution`, `pipeline.executors`, `pipeline.stores`, and `cli`.
- Defer deeper nested packages such as config recipes/instantiate, I/O sources/codecs, concrete stores, and concrete executors to their owning phases unless an import-safe unsupported stub is required by public import tests.
- Define `RecordID`, `ResourceKey`, `CodecKey`, `ArtifactID`, `ArtifactType`, `RunID`, and `StageID` as simple aliases only.
- Define `LoomError`, `ValidationError`, `ContractError`, `ArtifactError`, `ConfigError`, `PipelineError`, `ExecutionError`, and `IOErrorBase`.
- Define `utc_now`, `utc_timestamp`, `safe_timestamp_for_path`, and `parse_timestamp`.
- Make deferred callables raise a clear `LoomError` subclass when called while their modules still import cleanly.

## In-Scope Work

- Create `src/loom/ids.py` with simple string type aliases using `typing.TypeAlias` or equivalent type-only notation. Do not use `NewType`, wrapper classes, enums, or validation logic.
- Create `src/loom/errors.py` with the broad root hierarchy named by the full plan. Keep it standard-library only and safe for any subsystem to import.
- Create `src/loom/timestamps.py` using only `datetime` from the standard library. All authored timestamp strings should represent timezone-aware UTC instants.
- Create package skeleton `__init__.py` files for:
  - `src/loom/records`
  - `src/loom/provenance`
  - `src/loom/serialization`
  - `src/loom/io`
  - `src/loom/config`
  - `src/loom/pipeline`
  - `src/loom/pipeline/graph`
  - `src/loom/pipeline/planning`
  - `src/loom/pipeline/execution`
  - `src/loom/pipeline/executors`
  - `src/loom/pipeline/stores`
  - `src/loom/cli`
- Add unsupported stubs for the documented future config public entrypoints `compose_config`, `instantiate`, and `register_recipe` from `loom.config`. These callables should raise `ConfigError` with a concise unsupported-feature message until their owning config phases implement real behavior. Re-export `ConfigError` from `loom.config` because the error class exists in this phase and is part of the future config public path.
- Keep `src/loom/cli/__init__.py` import-safe, but do not add functional CLI parsing, `main.py`, command modules, or CLI callables in this phase.
- Keep `src/loom/__init__.py` limited to package metadata in this phase, currently `__version__`. Do not re-export unimplemented primitives such as `ResourceRef`, `Record`, `ArtifactRef`, `Fingerprint`, or `hash_mapping`, and do not re-export helper modules from the top level.
- Add focused tests for imports, import boundaries, errors, ID aliases, timestamp helpers, and unsupported stubs.
- Keep all tests and implementation domain-neutral.

## Out-of-Scope Work

- No `ResourceRef`, `ArtifactRef`, `Record`, manifests, provenance models, fingerprints, protocols, serialization behavior, config composition, recipes, target instantiation, URI parsing, sources, codecs, pipeline specs, graph validation, planning, execution, stores, concrete executors, plugin loading, or functional CLI behavior.
- No public `ensure_utc`, `ErrorContext`, diagnostics context fields, `to_dict`, `SerializationError`, `LoomIOError`, `FingerprintError`, `ProvenanceError`, `PluginError`, `ResourceError`, or subsystem-specific concrete errors. Feature documents may describe these later shapes, but Phase 1 implements only the names required by the canonical source phase.
- No new runtime dependencies or optional dependency extras.
- No deep nested package creation beyond the explicit Phase 1 skeleton list unless needed for a public import-safe unsupported stub.
- No domain-specific fixtures, project package imports, downstream examples, datasets, model/report helpers, or workflow semantics.
- No broad refactors, formatting churn, roadmap rewrites, or changes to phase status in the full implementation plan.
- No full validation or PR preparation during this planning stage.

## Assumptions

- The local `develop` checkout at `4878e95eda64c3d8d969fcfcc658d6b082a7f310` is the manager-approved base because `git fetch origin` is unavailable in this environment.
- Unsupported stubs are acceptable only where they protect a documented public import path; empty import-safe packages are preferred for future internal modules.
- `IOErrorBase` is intentionally named to avoid shadowing Python's built-in `IOError` while still providing a broad catchable root for `loom.io`.
- Timestamp helpers may raise `ValueError` for invalid or ambiguous timestamp input; the phase does not need a richer timestamp-specific error hierarchy.
- Top-level `loom` should remain minimal. Public imports for this phase should be tested from their owning modules without forcing broad `loom.__init__` re-exports.
- Empty package skeletons should expose no public names by default. Use empty `__all__` values for skeleton packages unless a package has an explicit Phase 1 public name.

## Design Impact

This phase establishes low-level module boundaries that future phases can rely on without creating runtime coupling. The package skeleton makes planned subsystem import paths real, while broad errors and timestamp/id helpers provide shared vocabulary that remains standard-library only.

The primary import-boundary impact is defensive: tests should prove that `import loom` does not import `loom.config`, `loom.pipeline`, `loom.cli`, plugin discovery, optional backends, or downstream project packages. That protects the full plan's public API policy before higher-level behavior exists.

## Future Compatibility

- Simple ID aliases keep future validation or wrapper types possible, but do not force downstream code through premature constructors in v0.
- Broad error roots let subsystem phases add precise concrete exceptions later without breaking catch-all handling.
- UTC timestamp helpers provide a single persisted metadata convention for run stores, provenance, logs, and future executor paths.
- Import-safe package skeletons let future phases grow modules into packages or add implementations behind stable public paths.
- Unsupported stubs make deferred public callables fail explicitly today and can be replaced by real implementations in their owning phases without changing import locations.

## Alternatives Rejected

- Early config dependencies: rejected because Phase 4 owns config dependencies and behavior.
- `NewType`, enums, or identifier wrapper classes: rejected because the v0 plan explicitly starts with simple aliases only.
- Runtime registries, plugin discovery, concrete stores, codecs, or executors: rejected because those belong to later subsystem phases.
- Functional CLI commands: rejected because v0 keeps CLI modules import-safe and unsupported.
- Re-exporting future primitives from `loom.__init__` before implementation: rejected because it would create misleading public API promises and could pull in future subsystem imports too early.
- Creating the full target source tree including deeper packages: rejected because `docs/structure.md` says not to add empty placeholders unless a phase needs the import path or unsupported stub.
- Implementing the richer `docs/features/errors.md` Phase 1 model now: rejected because the approved v0 plan narrowed this phase to the named broad roots, leaving structured error context for a later phase when concrete call sites exist.
- Making `ensure_utc` public now: rejected because the canonical phase lists only `utc_now`, `utc_timestamp`, `safe_timestamp_for_path`, and `parse_timestamp`. A private helper is acceptable if it keeps the public functions simple.

## Debt Introduced

- Unsupported stubs are intentional temporary debt. Revisit each stub when the owning phase implements the corresponding subsystem and replace it with real behavior or remove it from the public surface if the refined plan narrows the API.
- Import-safe empty packages may exist before behavior. Revisit in each subsystem phase to ensure package `__all__` exports and docs match implemented behavior rather than stale placeholders.
- Timestamp parsing can remain limited to loom-authored UTC metadata forms. Revisit only if multiple later call sites need path-safe timestamp parsing or additional precision policy.

## Reviewability

The implementation PR should be small and mostly structural. Reviewers should be able to inspect:

- new low-level modules and package `__init__.py` files;
- `src/loom/__init__.py` import cost and exports;
- focused tests proving errors, IDs, timestamps, unsupported stubs, and import boundaries; and
- absence of runtime dependencies, config behavior, pipeline behavior, store behavior, or domain-specific imports.

Avoid mixing this work with implementation of Phase 2 primitives or later runtime behavior.

## Files And Areas To Inspect

- `src/loom/__init__.py` for top-level cheap import behavior.
- `src/loom/ids.py` for simple alias definitions.
- `src/loom/errors.py` for broad catchable hierarchy.
- `src/loom/timestamps.py` for UTC-only formatting and parsing.
- `src/loom/*/__init__.py` and `src/loom/pipeline/*/__init__.py` for import-safe skeletons and narrowly scoped unsupported stubs.
- `tests/package/test_import.py` and any new `tests/package/test_public_api.py` or `tests/package/test_import_boundaries.py`.
- New unit tests under `tests/unit/loom/`.
- `pyproject.toml` and `Makefile` only to confirm existing suite markers and commands; avoid dependency or command changes unless implementation exposes a Phase 1 blocker.
- Source references:
  - `docs/structure.md` sections "Source-Tree Boundary", "Repository Layout", "Target Source Tree", "Import and Dependency Shape", "Public API Policy", "Module Responsibilities", "CLI", "Test Layout", and "Review Checklist".
  - `docs/loom.md` sections 1, 2, 3, 4, 12, and 14.
  - `docs/features/core-model.md`, `docs/features/errors.md`, `docs/features/timestamps.md`, `docs/features/protocols.md`, `docs/features/testing.md`, and `docs/features/cli.md`.

## Implementation Steps

1. Add `src/loom/ids.py`.
   - Define `RecordID`, `ResourceKey`, `CodecKey`, `ArtifactID`, `ArtifactType`, `RunID`, and `StageID` as aliases of `str`, for example `RecordID: TypeAlias = str`.
   - Export exactly those names through `__all__` in the same order.

2. Add `src/loom/errors.py`.
   - Define `LoomError` as the root for intentional `loom` exceptions.
   - Define `ValidationError`, `ContractError`, `ArtifactError`, `ConfigError`, `PipelineError`, `ExecutionError`, and `IOErrorBase` under `LoomError`.
   - Keep constructors inherited from `Exception`; use standard exception messages and Python exception chaining. Do not add context objects, error codes, hints, serialization helpers, or a diagnostics framework in Phase 1.
   - Export exactly the broad hierarchy through `__all__`.

3. Add `src/loom/timestamps.py`.
   - Implement `utc_now() -> datetime` as timezone-aware UTC.
   - Implement `utc_timestamp(value: datetime | None = None, *, timespec: str = "seconds") -> str` with `Z` suffix and UTC normalization.
   - Implement `safe_timestamp_for_path(value: datetime | None = None, *, timespec: str = "seconds") -> str` using `YYYYMMDDTHHMMSSZ`, `YYYYMMDDTHHMMSSmmmZ`, or `YYYYMMDDTHHMMSSffffffZ` for seconds, milliseconds, and microseconds respectively.
   - Accept exactly these `timespec` values in Phase 1: `seconds`, `milliseconds`, and `microseconds`. Invalid values raise `ValueError` with a clear unsupported-timespec message.
   - Implement `parse_timestamp(value: str) -> datetime` for loom-authored UTC metadata strings with `Z` or `+00:00`. Do not parse path-safe timestamp strings in Phase 1.
   - Normalize aware non-UTC datetimes to UTC, reject naive datetimes through `ValueError`, and do not silently assume local time.
   - Export exactly `utc_now`, `utc_timestamp`, `safe_timestamp_for_path`, and `parse_timestamp`; any normalization helper should be private.

4. Add package skeletons.
   - Create only the Phase 1 package paths listed in the source plan.
   - Keep module imports cheap and standard-library only.
   - Avoid importing sibling high-level subsystems from package `__init__.py` files.
   - For empty skeleton packages, define no public exports beyond an empty `__all__`.

5. Add deferred unsupported stubs for `loom.config`.
   - Expose `ConfigError`, `compose_config`, `instantiate`, and `register_recipe` from `src/loom/config/__init__.py`.
   - Use simple unsupported signatures such as `def compose_config(*_args: object, **_kwargs: object) -> NoReturn: ...`, and the same shape for `instantiate` and `register_recipe`. Do not model the future full API before Phase 4.
   - `compose_config` should raise `ConfigError` explaining that config composition is not implemented until Phase 4.
   - `instantiate` should raise `ConfigError` explaining that target instantiation is not implemented until Phase 4.
   - `register_recipe` should raise `ConfigError` explaining that recipe registration is not implemented until Phase 5.
   - Set `loom.config.__all__` to exactly `["ConfigError", "compose_config", "instantiate", "register_recipe"]`.
   - Do not add CLI callables in Phase 1; `loom.cli` only needs to import cleanly.
   - Do not stub `ResourceRef`, `Record`, `ArtifactRef`, `PipelineSpec`, `StageSpec`, `StageContext`, `PipelineRunner`, codecs, stores, or executors as behavioral placeholders; their owning phases should add real public objects.

6. Update `src/loom/__init__.py`.
   - Keep `__version__` available.
   - Keep `__all__` limited to `["__version__"]` for this phase.
   - Ensure `__all__` matches the actual top-level public surface.

7. Add package and unit tests.
   - Package tests should assert `import loom` succeeds, `__version__` remains in `__all__`, `py.typed` remains included, and documented Phase 1 module imports are stable.
   - Import-boundary tests should assert top-level import does not load `loom.config`, `loom.pipeline`, or `loom.cli` as side effects. Prefer a clean Python subprocess for this assertion so prior imports from other tests cannot hide side effects.
   - Unit tests should cover ID aliases, error inheritance, timestamp formatting/parsing/rejection, and unsupported stub failure types/messages.

8. Run targeted checks during implementation.
   - Run `make test-package`.
   - Run `make test-unit`.
   - Run narrower direct tests while iterating when useful, for example `uv run pytest tests/unit/loom/test_timestamps.py`.

9. Leave final PR validation to `loom_pr_preparer`.
   - Before PR preparation, run `make validate-pr`.
   - Before PR preparation, run `make test-summary`.

## Test Plan

### Package Suite

- Required for this phase.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
- Assertions:
  - `import loom` succeeds and remains cheap.
  - `loom.__version__` and `loom.__all__` are coherent, with top-level `__all__` exactly `["__version__"]` in this phase.
  - `src/loom/py.typed` remains packaged.
  - `from loom.ids import ...`, `from loom.errors import ...`, `from loom.timestamps import ...`, and `from loom.config import ConfigError, compose_config, instantiate, register_recipe` work.
  - Deferred package imports such as `import loom.config`, `import loom.pipeline`, `import loom.pipeline.graph`, `import loom.pipeline.planning`, `import loom.pipeline.execution`, `import loom.pipeline.executors`, `import loom.pipeline.stores`, and `import loom.cli` succeed without side effects.
  - Top-level `import loom` does not eagerly import config, pipeline, CLI, plugin discovery, optional backends, or downstream project packages.
  - Empty skeleton packages expose empty `__all__` values; no package test should import future public objects that Phase 1 has not implemented.
- Targeted command: `make test-package`.

### Unit Suite

- Required for this phase.
- Expected paths:
  - `tests/unit/loom/test_ids.py`
  - `tests/unit/loom/test_errors.py`
  - `tests/unit/loom/test_timestamps.py`
  - `tests/unit/loom/test_deferred_stubs.py`
- Assertions:
  - ID aliases are simple aliases, are `str` at runtime, and accept ordinary strings without runtime wrapper construction.
  - ID module `__all__` contains exactly the seven Phase 1 aliases.
  - Error classes inherit from `LoomError`, and `LoomError` inherits from `Exception`.
  - Error module `__all__` contains exactly the eight Phase 1 error roots.
  - `IOErrorBase` does not shadow or replace Python built-ins; no `IOError` alias is introduced.
  - `utc_now` returns an aware UTC `datetime`.
  - `utc_timestamp` returns parseable UTC metadata strings with a `Z` suffix.
  - `utc_timestamp` normalizes aware non-UTC datetimes, preserves requested seconds/milliseconds/microseconds precision, and rejects unsupported `timespec` values.
  - `safe_timestamp_for_path` returns strings without path-hostile punctuation such as colons or spaces and uses the exact seconds/milliseconds/microseconds shapes named above.
  - `parse_timestamp` accepts loom-authored UTC forms and returns timezone-aware UTC datetimes.
  - `parse_timestamp` accepts canonical `Z` and `+00:00` metadata forms, but path-safe timestamp parsing remains out of scope.
  - Naive datetimes or invalid timestamp strings fail clearly with `ValueError`.
  - Unsupported stubs raise `ConfigError`, a `LoomError` subclass, when called with no args, positional args, or keyword args.
  - Stub error messages name the deferred feature and owning future phase.
- Targeted command: `make test-unit`.

### Contract Suite

- Intentionally deferred for this phase.
- Reason: Phase 1 does not implement extension-point contracts such as `Codec`, `DataSource`, `Stage`, `ArtifactStore`, `RunStore`, or `Executor`. Adding contract tests now would either be empty or force fake behavior from future phases.
- Expected command behavior before future contract tests exist: `make test-contract` may report the suite as `not present` through the repository harness.

### Integration Suite

- Intentionally deferred for this phase.
- Reason: Phase 1 has no cross-component runtime collaboration. Import-boundary behavior is covered by package and unit tests without needing config, pipeline, store, or executor integration.
- Expected command behavior before future integration tests exist: `make test-integration` may report the suite as `not present`.

### E2E Suite

- Intentionally deferred for this phase.
- Reason: Phase 1 has no functional CLI, config composition, pipeline execution, stores, or synthetic workflow to exercise end to end.
- Expected command behavior before future e2e tests exist: `make test-e2e` may report the suite as `not present`.

### Opt-In Suites

- Intentionally deferred for this phase.
- Markers affected: `slow`, `slurm`, `network`, and `optional_dependency`.
- Reason: Phase 1 must remain dependency-free, local, and import-focused. It should not require network access, optional dependency installation, SLURM, subprocess backends, remote services, large data, or slow acceptance tests.
- If any opt-in test is accidentally needed, record why in the implementation PR body and keep it outside the default PR gate unless the manager explicitly changes the validation policy.

## Risks

- Over-stubbing future APIs could make unsupported placeholders look like real public contracts. Mitigation: expose only documented callables that tests require and make every unsupported call fail loudly.
- Top-level exports could accidentally import high-level subsystems. Mitigation: keep `loom.__init__` minimal and test `sys.modules` import boundaries.
- Timestamp helpers can be subtly wrong around naive datetimes or offsets. Mitigation: unit-test aware UTC input, non-UTC aware normalization, invalid input, and parse round trips.
- Empty package skeletons can create stale structure. Mitigation: create only Phase 1 paths and let owning future phases add deeper modules.
- Feature documents describe broader future public APIs than this phase owns. Mitigation: follow the canonical implementation plan, record explicit deferrals, and avoid tests that force future behavior early.
- `git fetch origin` was unavailable. Mitigation: the manager preflight already found local `develop` clean and tracking `origin/develop`; this plan records the limitation and proceeds from the local base as the prompt allows.

## Validation Commands

Implementation-time targeted commands:

```sh
make test-package
make test-unit
uv run pytest tests/unit/loom/test_timestamps.py
```

Optional suite visibility commands if the executor wants to confirm intentional deferrals:

```sh
make test-contract
make test-integration
make test-e2e
```

Required before PR preparation:

```sh
make validate-pr
make test-summary
```

`make validate-pr` is expected to run Ruff, Pyright, the default Pytest suite, and build. `make test-summary` is expected to write suite-level evidence for the PR body. If either command cannot be run, the PR preparation agent must record the exact reason in the phase plan completion notes and PR body.

## Refinement And Review Budget Status

- Phase implementation refinement: used.
- PR review: used.

Implementation refinement was consumed on 2026-05-03 by the bounded
`loom_phase_refiner` pass. PR review was consumed on 2026-05-03 by local
manager review before the local squash merge.

## Handoff Notes For Executor

Safe implementation slices:

1. Low-level helpers.
   - Files: `src/loom/ids.py`, `src/loom/errors.py`, `src/loom/timestamps.py`.
   - Tests: `tests/unit/loom/test_ids.py`, `tests/unit/loom/test_errors.py`, and `tests/unit/loom/test_timestamps.py`.
   - Commit shape: one `feat:` commit is appropriate if the helper modules and their tests are reviewed together.

2. Package skeletons and config stubs.
   - Files: `src/loom/records/__init__.py`, `src/loom/provenance/__init__.py`, `src/loom/serialization/__init__.py`, `src/loom/io/__init__.py`, `src/loom/config/__init__.py`, `src/loom/pipeline/__init__.py`, `src/loom/pipeline/graph/__init__.py`, `src/loom/pipeline/planning/__init__.py`, `src/loom/pipeline/execution/__init__.py`, `src/loom/pipeline/executors/__init__.py`, `src/loom/pipeline/stores/__init__.py`, and `src/loom/cli/__init__.py`.
   - Tests: `tests/package/test_public_api.py` and `tests/unit/loom/test_deferred_stubs.py`.
   - Commit shape: one `feat:` commit is appropriate for import-safe package creation and unsupported stubs.

3. Import-boundary and package-surface guardrails.
   - Files: `src/loom/__init__.py` only if needed to keep `__all__` exact, plus `tests/package/test_import.py` and `tests/package/test_import_boundaries.py`.
   - Tests: `make test-package`; use a clean subprocess in the import-boundary test.
   - Commit shape: one `test:` commit is appropriate if this slice only adds guardrail tests.

Choices not to revisit during execution:

- Keep Phase 1 limited to skeletons, broad errors, ID aliases, timestamp helpers, config unsupported stubs, and tests.
- Keep `loom.__init__.__all__` exactly `["__version__"]`.
- Keep empty skeleton package `__all__` values empty.
- Keep `loom.config.__all__` exactly `["ConfigError", "compose_config", "instantiate", "register_recipe"]`.
- Keep config stub signatures as variadic `object` inputs returning `NoReturn`; do not model future config arguments.
- Do not create `config/recipes`, `config/instantiate`, `io/sources`, `io/codecs`, concrete store/executor modules, `cli/main.py`, or command modules.
- Do not implement public `ensure_utc`, `ErrorContext`, concrete subsystem errors, protocols, primitives, serialization, config behavior, pipeline behavior, stores, or CLI behavior.
- Preserve the explicit suite deferrals for contract, integration, e2e, and opt-in suites.
- Keep the recorded `git fetch origin` limitation unless a later handoff successfully fetches and rebases before implementation.

If an ambiguity would require changing public API shape or widening phase scope,
stop and report the blocker rather than making a new design decision.

## Completion Notes

- Draft expanded phase plan created by `loom_phase_planner`.
- Final expansion completed by `loom_phase_plan_expander`.
- Important refinements: exact public export lists, timestamp precision policy, config stub signatures/messages, explicit feature-document deferrals, and executor implementation slices.
- Implementation summary:
  - Added `src/loom/ids.py`, `src/loom/errors.py`, and `src/loom/timestamps.py`.
  - Added import-safe package skeletons for all Phase 1 paths.
  - Added Phase 1 config stubs in `src/loom/config/__init__.py` with unsupported-feature `ConfigError` raises.
  - Added package-level and unit tests at `tests/package` and `tests/unit/loom` to validate imports, boundaries, aliases, errors, timestamps, and deferred-call failure modes.
  - Refinement pass constrained `parse_timestamp` to the authored extended UTC metadata form so path-safe timestamp strings remain out of scope, added focused coverage for empty skeleton exports, invalid timestamp strings, and absence of a public `IOError` alias, and configured Pyright to resolve the uv-managed `.venv` used by the repository validation target.
- Test evidence:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/test_timestamps.py`: passed, 9 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-package`: passed, 7 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-unit`: passed, 17 passed.
- Validation evidence:
  - Manager rerun before refinement: `UV_CACHE_DIR=/tmp/uv-cache make test-package` passed, 6 passed.
  - Manager rerun before refinement: `UV_CACHE_DIR=/tmp/uv-cache make test-unit` passed, 15 passed.
  - Refinement validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; Ruff passed, Pyright passed with 0 errors, default tests passed with 24 passed, and `uv build` produced sdist and wheel.
  - PR-prep validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; Ruff passed, Pyright reported 0 errors, default tests passed with 24 passed, and `uv build` produced sdist and wheel.
  - Pre-merge validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; Ruff passed, Pyright reported 0 errors, default tests passed with 24 passed, and `uv build` produced sdist and wheel.
- Test-summary evidence:
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote `build/test-summary.md`.
  - Suite table: package passed, unit passed, contract not present, integration not present, e2e not present.
  - Package suite passed with 7 tests; unit suite passed with 17 tests.
  - Pre-merge rerun: `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package passed, unit passed, and contract/integration/e2e not present.
- Accepted risks:
  - Unsupported config stubs remain temporary debt until Phase 4 (`compose_config`, `instantiate`) and Phase 5 (`register_recipe`).
  - Empty skeleton packages remain temporary structure until each owning future phase adds behavior.
  - Contract, integration, and e2e suites remain intentionally absent because Phase 1 contains no runtime contracts or cross-component behavior.
  - This branch remains based on local `develop` at `4878e95eda64c3d8d969fcfcc658d6b082a7f310`; earlier `git fetch origin` failed because SSH authentication was unavailable.
  - `pyproject.toml` now points Pyright at the repository `.venv` so the existing uv-managed validation environment resolves consistently.
- PR status:
  - Target: `develop`.
  - Branch: `codex/add-foundation-skeleton`.
  - Worktree: `/home/samcantrill/work/loom-worktrees/add-foundation-skeleton`.
  - Body path: `docs/phases/add-foundation-skeleton-pr-body.md`.
  - `gh pr create` was attempted on 2026-05-03 but failed because `gh` is not authenticated; no alternate authenticated GitHub PR tooling is configured.
  - Local manager PR review passed on 2026-05-03.
  - Locally squash-merged into `develop` as `61b76ac` on 2026-05-03.
- Budget status:
  - Phase implementation refinement: used.
  - PR review: used by local manager review.
- Cleanup:
  - Dedicated worktree removed.
  - Stale worktree metadata pruned.
  - Local `codex/add-foundation-skeleton` branch retained because deleting the
    branch after a squash merge would discard the only refs to the unsquashed
    phase commits and explicit deletion approval was not available.
- Remaining blockers: none for local merge. Remote PR creation and push were
  not performed because `gh` is not authenticated and the local `develop`
  checkout also contains unrelated unpushed v1-plan work.
