# Phase 2 Execution Plan: Typed Resource Entries

## Metadata

- Status: draft phase execution plan
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 2: Typed Resource Entries`
- Branch: `codex/typed-resource-entries`
- Worktree: `/home/samcantrill/work/loom-worktrees/typed-resource-entries`
- Phase execution plan path: `docs/phases/typed-resource-entries.md`
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- Source phase: Phase 2 - Typed Resource Entries
- Stack predecessor: none; Phase 1 is merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path because this is a breaking public resource schema refactor
- Successor dependency notes: later phases may build runtime options, descriptors, capability checks, preflight wiring, runtime metadata, and CLI/config runtime mapping on top of the entry model after this PR is open or merged
- Plan quality gate: passed on 2026-05-07 after initial review, refinement, and confirmation review
- Plan quality gate loop budget: initial review used; gate refinement pass used; confirmation review used
- Draft pass: completed by `loom_phase_planner` in this artifact
- Refine pass: pending after draft
- Setup limitations: none; `gh auth status` passed with network access, `gh auth setup-git` completed, `git fetch origin` completed, and local `develop` matched `origin/develop` at `60a23ba`
- Blockers: none known

## Objective

Hard-swap Loom's public runtime resource schema from fixed CPU, memory, GPU, and custom fields to immutable typed resource entries while preserving plain-data serialization, deterministic validation, and semantic fingerprint non-impact.

## Full-Plan Context

Phase 1 already established the import-light runtime package boundary and left resource behavior unchanged. This phase performs the isolated v4 resource schema break so later `RunOptions`, runtime profiles, executor descriptors, capability diagnostics, preflight checks, and `runtime.json` work can depend on a stable typed resource model instead of carrying the old `cpus` / `memory_mb` / `gpus` fields forward.

Future-phase work must stay out of this PR: no `RunOptions`, no profiles, no executor descriptors or capability checks, no resource capability preflight, no `runtime.json`, and no broad CLI/config runtime mapping beyond fixing existing resource schema examples or tests that currently construct resources.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 PR #70 is merged into `develop`
- Why this base branch is correct: all earlier v4 phase work is merged and the assignment names `develop` as both base and target
- Retarget/rebase plan after predecessor merge: not needed for this root phase unless `develop` advances before PR preparation; then rebase onto updated `develop` and rerun validation
- Branch cleanup constraints: branch may be deleted after squash merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: hard-swap the resource schema to typed resource entries.
- Required scope: implement `ResourceEntry(kind, amount, unit, attributes)`, replace canonical `ResourceRequest` with `entries={...}`, define kind syntax and explicit validator registry/composition behavior, add built-in `cpu`, `memory`, and `gpu` validation, reject old resource keys and constructor aliases, update `StageSpec`, `RuntimeRequest`, exports, docs, examples, and tests.
- Required checkpoints: public exports expose `ResourceEntry`; authored canonical entry syntax parses; entries keys match `ResourceEntry.kind`; old fields are rejected everywhere; default registry is deterministic and isolated; docs and fixtures no longer advertise the old schema as current v4 behavior.
- Acceptance criteria: the implementation satisfies the Phase 2 acceptance list in `implementation-plan-v4.md`, including unchanged semantic fingerprints and no future-phase runtime/capability behavior.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/resources.py` owns the old `ResourceRequest(cpus, memory_mb, gpus, custom)` schema and `parse_resource_request`; `src/loom/pipeline/specs.py` stores authored `StageSpec.resources` as frozen plain data and exposes `StageSpec.resource_request`; `src/loom/pipeline/runtime/_models.py` serializes `RuntimeRequest.resources` through `ResourceRequest.to_dict`; `src/loom/pipeline/__init__.py` and `src/loom/pipeline/runtime/__init__.py` expose public imports.
- Existing tests or harness behavior: `tests/unit/loom/pipeline/test_runtime_resources.py`, `tests/unit/loom/pipeline/test_specs.py`, package import tests, fingerprint tests, and integration config fixtures currently encode old resource fields and must be migrated or explicitly asserted rejected.
- Import-boundary or dependency constraints: keep resources import-light and domain-neutral; do not import CLI, diagnostics, executor implementations, plugins, or optional backends; use existing serialization helpers for plain data and immutability; do not add heavyweight dependencies.

## In-Scope Work

- Add immutable `ResourceEntry` with `kind`, `amount`, optional `unit`, and plain-data-compatible `attributes`.
- Replace canonical `ResourceRequest` construction and serialization with `ResourceRequest(entries={...})`.
- Define and enforce resource-kind syntax: lowercase ASCII identifier segments separated by dots; built-ins use unqualified `cpu`, `memory`, and `gpu`.
- Define deterministic explicit validator registry/composition behavior, including no hidden process-global mutation, duplicate registration failure, custom registry isolation, and unregistered-kind rejection unless the caller supplies a composed registry before validation.
- Add built-in validators for `cpu`, `memory`, and `gpu` covering amount, unit, and attributes semantics.
- Reject old authored and constructor fields: `cpus`, `memory_mb`, `gpus`, and `custom`.
- Update `StageSpec.resources`, `StageSpec.resource_request`, `RuntimeRequest.resources`, package exports, public docs, examples, and affected fixtures for entry semantics.
- Preserve immutable plain-data storage and serialization for stage resources, runtime resources, and resource attributes.
- Preserve existing semantic fingerprint behavior: resource changes remain excluded from semantic fingerprints by default.

## Out-of-Scope Work

- `RunOptions`, runtime profiles, stage runtime options, environment models, executor descriptors, capability checks, preflight wiring, and `runtime.json`.
- CLI/config runtime mapping beyond resource schema fixes required for existing tests, fixtures, and docs.
- Plugin discovery, entry point loading, or global third-party validator registration.
- Executor-specific resource interpretation, local scheduling behavior, SLURM/container mapping, retry, timeout, wall-time, or adapter schema validation.
- Compatibility aliases or migration shims that keep old resource constructor fields working.

## Assumptions

- The resource schema version may stay at the current version only if the serialized document shape is intentionally the v4 replacement for the pre-v4 local contract; otherwise the executor should choose the smallest versioning update consistent with existing serialization helpers and tests.
- The canonical authored form should make the resource mapping key the stable identity and require it to equal the entry's `kind`; any shorthand that omits `kind` should be avoided unless the refine pass explicitly accepts it.
- Built-in semantics should be scheduler-neutral: `cpu` and `memory` require positive amounts, `gpu` permits non-negative or positive amounts only if the refine pass confirms the intended zero-GPU representation; unsupported attributes fail unless a built-in validator explicitly owns them.
- Error messages should be path-aware enough for authored config and serialized runtime failures, but they do not need a new error class.

## Scope Contract

The public contract changes in this phase. `loom.pipeline.resources` must expose `ResourceEntry`, `ResourceRequest`, and `parse_resource_request`; `loom.pipeline` must re-export `ResourceEntry` and the entry-based `ResourceRequest`. `ResourceRequest` no longer accepts `cpus`, `memory_mb`, `gpus`, or `custom` as constructor inputs or serialized/authored fields.

`ResourceRequest.to_dict()` and `ResourceRequest.from_dict()` must round-trip a schema-versioned plain-data document with an `entries` mapping. Authored `StageSpec.resources` may remain stored as frozen plain data, but parsing and `StageSpec.resource_request` must validate and return the typed entry request. `RuntimeRequest.resources` remains a `ResourceRequest` and must serialize the entry-based resource request.

Validation must be explicit and deterministic. The default built-in registry is immutable or copy-on-write; custom callers can compose a registry and pass it to resource parsing/validation; duplicate registration for a kind fails; validators never leak between calls; unregistered kinds fail with path-aware errors. Resource shape validation stays separate from future executor capability validation.

## Design Impact

- Maintainability: consolidates resource shape, parsing, and validator ownership in `loom.pipeline.resources` instead of spreading resource fields across runtime, stage, docs, and future executor phases.
- Extensibility: future resource kinds extend through explicit validators and registry composition rather than new `ResourceRequest` fields or untyped `custom` payloads.
- Domain neutrality: built-in kinds remain scheduler-neutral declarations; executor-specific capability and translation behavior remains deferred.
- Source-tree boundaries: resource models stay in `loom.pipeline.resources`; runtime request integration stays in `loom.pipeline.runtime`; docs and tests update only the public schema surface.

## Future Compatibility

- Future adapter or plugin phases can register qualified kinds through composed registries without mutating global state.
- Future executor descriptors can evaluate validated entry kinds as capabilities without changing the resource data model.
- Future runtime profiles and stage runtime options can embed `ResourceRequest(entries=...)` without inheriting old aliases.
- Future migration tooling or docs can explain old-field conversion, but runtime compatibility aliases should remain absent unless a later plan deliberately changes the v4 break.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep fixed `cpus`, `memory_mb`, and `gpus` fields | Carries an inflexible schema into future schedulers, containers, plugins, and capability checks. |
| Preserve compatibility aliases for old keys | Conflicts with the v4 hard-swap goal and would leave two public schemas for later phases to support. |
| Keep `custom` as the extension mechanism | Makes validation and executor capability diagnostics ambiguous. |
| Use process-global mutable validator registration | Risks cross-test leakage, import-order dependence, and nondeterministic plugin behavior. |
| Combine resource schema validation with executor capability checks | Would couple neutral resources to future executor-specific policy and expand this phase beyond scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Existing downstream configs must migrate manually from old resource keys | The clean v4 schema break is intentional and avoids long-lived aliases. | Revisit only if docs or migration tooling becomes necessary after downstream adoption feedback. |
| No third-party validator discovery | V4 needs explicit deterministic composition before plugin loading exists. | Revisit in plugin discovery or first adapter phase that needs externally supplied kinds. |
| Built-in resource validators are intentionally minimal | Executor capability and scheduler-specific semantics are later-phase responsibilities. | Revisit when Phase 6 capability diagnostics or scheduler/container phases need richer capability metadata. |

## Reviewability

- Expected PR size and shape: medium schema-refactor PR centered on `resources.py`, stage/runtime integration, public exports, tests, docs, and fixtures; no executor/preflight/profile implementation.
- Files and areas to inspect: `src/loom/pipeline/resources.py`, `src/loom/pipeline/specs.py`, `src/loom/pipeline/runtime/_models.py`, `src/loom/pipeline/__init__.py`, `src/loom/pipeline/runtime/__init__.py`, resource/stage/runtime/package tests, integration config fixtures, `docs/features/runtime-resources.md`, `docs/features/pipeline.md`, and canonical examples that mention runtime resources.
- Scope-control checks: reject old keys instead of supporting aliases; no `RunOptions` or descriptor classes; no CLI flags; no semantic fingerprint inclusion; no global mutable validator state.

## Implementation Steps

1. Replace the resource model surface with `ResourceEntry`, entry-based `ResourceRequest`, kind syntax validation, plain-data freezing/thawing, and schema-versioned entry serialization.
2. Add the explicit validator registry and built-in `cpu`, `memory`, and `gpu` validators with deterministic composition, duplicate-kind failure, unregistered-kind failure, and path-aware error behavior.
3. Update stage and runtime integration so `StageSpec.resources`, `StageSpec.resource_request`, and `RuntimeRequest.resources` validate and serialize entry-based requests while preserving frozen plain-data storage.
4. Update public exports and package/import tests so `ResourceEntry`, entry-based `ResourceRequest`, and `parse_resource_request` are available from the intended facades.
5. Migrate unit, contract, integration, e2e fixtures, and fingerprint tests from old resource fields to entry syntax, adding explicit old-key rejection coverage.
6. Update `docs/features/runtime-resources.md`, `docs/features/pipeline.md`, and related canonical examples so the v4 resource contract is entry-based and old schemas are absent or clearly historical.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `ResourceEntry` and entry-based `ResourceRequest` are exported through public facades; resource and runtime imports remain import-light and do not pull forbidden modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/test_runtime_resources.py`, `tests/unit/loom/pipeline/test_specs.py`, `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`, plus any focused resource registry test module the executor adds
- Required assertions or deferral reason: `ResourceEntry` immutability and plain-data attributes; `ResourceRequest(entries=...)` round-trips; authored entry syntax parses; entry keys must match `ResourceEntry.kind`; old authored and constructor fields fail; invalid kind syntax fails; built-in validators enforce `cpu`, `memory`, and `gpu`; unregistered kinds fail without a custom registry; duplicate registration fails; custom registry composition is isolated; `StageSpec.resource_request` and `RuntimeRequest` serialization use entries; resource changes still do not alter semantic fingerprints.

### Contract Suite

- Status: required
- Expected paths: existing contract-style serialization/plain-data tests if present, or focused resource tests under `tests/unit/loom/pipeline/` when the repo does not have a separate contract directory
- Required assertions or deferral reason: resource requests and entries expose only plain-data-compatible serialized forms, freeze nested attributes, reject non-plain-data values, and cannot be mutated through stored mappings.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/config/` and any integration fixtures or composed pipeline configs that declare resources
- Required assertions or deferral reason: existing local pipeline/config resource fixtures use entry syntax and still compose/validate; old resource fields in authored config fail with clear errors.

### E2E Suite

- Status: required
- Expected paths: existing local pipeline e2e tests selected by the default PR validation gate
- Required assertions or deferral reason: current local e2e remains green after fixture migration; no new external scheduler/container e2e is introduced.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: Phase 2 is local, domain-neutral schema work and does not require SLURM, Docker, Apptainer, network, plugin discovery, or other opt-in backends.

## Risks

- This is a breaking public schema change; missed old-schema docs or examples could mislead users after v4.
- Validator registry API shape has durable public impact; the refine pass should scrutinize amount/unit/attribute semantics and whether registry composition is sufficiently explicit without becoming over-engineered.
- Error paths must be useful for both authored stage resources and serialized `RuntimeRequest` documents.
- Updating fixtures broadly could accidentally change semantic fingerprint expectations; fingerprint tests must pin non-impact.
- Supporting old aliases accidentally would undermine later phases and should be treated as a blocker.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/planning/test_planning_fingerprints.py
uv run pytest tests/integration/config
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: resource model and registry first; stage/runtime integration second; exports and tests third; docs/examples last.
- Tests to run with each slice: run focused resource unit tests after model/registry work, stage/runtime unit tests after integration, package tests after exports, integration config tests after fixture migration, and final PR validation before PR preparation.
- Decisions the executor must not revisit: no old resource aliases, no process-global mutable registry, no executor capability checks, no `RunOptions`, no runtime profiles, no semantic fingerprint impact.
- Conditions that require stopping for the manager: inability to define deterministic registry composition without a public-contract choice, contradiction between built-in validator semantics and the implementation plan, or broad fixture/doc migration that would pull in future runtime option behavior.
- Expanded-path refinement notes: the pending refine pass should focus on public registry API clarity, exact built-in amount/unit/attribute semantics, schema version decision, and whether the plan gives enough stop conditions for the breaking resource contract.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-07 by `loom_phase_planner`; committed as `plan: add phase execution plan`
- Final phase execution plan: pending refine pass
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- Blocker-resolution summary: none used
- PR preparation: pending
- Stack maintenance: none required yet
- Remaining blockers: none known
