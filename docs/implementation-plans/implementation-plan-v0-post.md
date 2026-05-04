# V0 Post-Implementation Architecture Limitations and Remediation Decisions

## Goal

Evaluate the current v0 implementation against the longer-term `loom` vision in
[`docs/loom.md`](../loom.md), [`docs/structure.md`](../structure.md), and the
post-v0 roadmap.

This is a pre-v1 architecture gate audit, remediation decision record, and
phased implementation plan. Individual phase execution plans should expand the
implementation detail for one phase at a time, but this document is the
controlling sequence for the v0-post hardening work.

## Context

The v0 runtime establishes a local Python API for trusted config composition,
static artifact DAGs, local run and artifact stores, conservative
same-run-directory resume, provenance capture, and local in-process execution.
That is intentionally narrower than the long-term design:

- functional CLI commands;
- runtime/resource profiles;
- subprocess, SLURM, Docker, and Apptainer execution;
- sweeps over many runs;
- plugin discovery;
- run catalogs and bundles;
- remote artifact stores;
- retry, timeout, cleanup, and runtime event policies.

The question for this gate is whether v0's local-first structures leave those
future directions open, or whether any current contracts should be corrected
before v1 and v2 build more public surface on top of them.

## Audit Method

Each finding records:

- current v0 decision or structure;
- why it was reasonable for v0;
- long-term limitation;
- user impact;
- affected roadmap versions;
- severity;
- gate decision;
- selected remediation.

Severity values:

```text
critical
high
medium
low
```

Gate decisions:

```text
must resolve before v1
resolve before later roadmap step
monitor
```

## Review Outcome

The selected direction is a dedicated v0-post hardening plan that must land
before v1 config-composition work proceeds. Breaking changes to existing v0 APIs
are allowed where they cleanly correct long-term contracts before CLI, workers,
catalogs, plugins, and remote stores build on them.

Cross-run artifact identity should be represented by a higher-level
`ArtifactAddress` value object in `loom.artifacts`, backed by the pair
`(run_id, artifact_id)`. Artifact IDs remain run-local, and artifact stores
remain bound to one run.

The amended phase plan uses eight phases. Documentation that defines package
ownership or public contracts must move with the phase that creates the
contract; the final hardening phase performs migration-note and roadmap cleanup
rather than carrying all structure updates.

## Selected Remediation Summary

| # | Finding | Selected direction |
|---|---|---|
| 1 | Local path-shaped store contracts | Break before v1; replace generic path contracts with capability-oriented store and context APIs. |
| 2 | Artifact store run scope and identity | Make `ArtifactStore` explicitly run-scoped; add `loom.artifacts.ArtifactAddress` for catalog/bundle identity. |
| 3 | Runner as high-policy coordinator | Do a broad pre-v1 internal decomposition while preserving `PipelineRunner` as the facade. |
| 4 | Planning policy concentration | Split planner policies before v1 and add a separate typed explanation surface. |
| 5 | Shallow immutability | Make frozen core refs and specs recursively immutable. |
| 6 | Persisted schema boilerplate | Add a central strict versioned plain-data schema layer with explicit migrations. |
| 7 | Global recipe registry state | Make explicit catalogs the reproducible path; keep global registration only as Python convenience. |
| 8 | Run metadata naming ambiguity | Rename before v1 to clear run-document and user-metadata APIs. |
| 9 | Blocked descendant state | Persist blocked stage outcome records for planned descendants. |
| 10 | Hard config dependencies | Move config dependencies behind optional extras before v1. |
| 11 | No-argument stage construction | Add an explicit `factory: {_target_: ..., init: {...}}` block separate from runtime `stage_config`. |
| 12 | Missing runtime/resource/event/lock abstractions | Add typed foundations, `loom.pipeline.events`, append-only local events, and store-capability locking. |

## Findings

### 1. Local Path-Shaped Store Contracts

Current decision:

- `RunStore` exposes local `Path` values for run directories, stage
  directories, artifact roots, config snapshots, provenance files, and log
  paths.
- `StageContext` exposes `run_dir`, `stage_dir`, and `output_path()` as local
  paths.

Why it was reasonable for v0:

- V0 is explicitly local-only and prioritizes inspectable run directories.
- Local paths make synthetic stages easy to author and debug.
- The file layout is useful for tests, examples, and early user trust.

Long-term limitation:

- Remote stores, subprocess workers, container executors, and SLURM jobs may
  need URI-oriented or staged-file capabilities rather than direct local paths.
- A remote `RunStore` would have to fake local `Path` methods or reject parts
  of the protocol.
- `StageContext.output_path()` encourages stage implementations to assume a
  shared writable filesystem.

User impact:

- Early users may write stages that directly manipulate local paths and become
  hard to move to subprocess, container, remote, or cluster execution.
- Projects that need object storage or staged worker files may have to wrap
  `loom` instead of implementing a clean store backend.

Affected roadmap versions:

- v3 local diagnostics and preflight;
- v4 runtime options and resources;
- v5 subprocess execution;
- v6-v7 SLURM;
- v12-v13 remote stores;
- v14-v15 container execution.

Severity: critical.

Gate decision: must resolve before v1.

Selected remediation:

- Break the generic path-shaped `RunStore` and `StageContext` contracts before
  v1.
- Replace them with capability-oriented APIs for artifacts, outputs, logs,
  temporary/workspace access, and durable run state.
- Keep local path helpers only on explicit local-only types or capabilities.
  The local run directory remains inspectable, but it is no longer the generic
  store protocol shape.

### 2. Artifact Store Run Scope and Artifact Identity

Current decision:

- `LocalArtifactStore` is constructed with one run's artifact root.
- Its methods still accept `run_id`, but managed paths are effectively
  `artifacts/STAGE/OUTPUT`.
- Managed artifact IDs are `stage/output`, not globally unique across runs.

Why it was reasonable for v0:

- Same-run-directory resume is the only supported reuse mode.
- Per-run artifact stores are simple and match the current run directory.
- Human-readable artifact IDs are easy to inspect.

Long-term limitation:

- A shared artifact store, remote store, bundle import/export, or run catalog
  cannot rely on `stage/output` as a durable identity.
- Cross-run cache reuse remains out of scope, but future users may still need
  unambiguous artifact lineage across many local runs.
- The API shape is ambiguous: either artifact stores are run-scoped and should
  not need `run_id`, or they are multi-run and should include run identity in
  storage policy.

User impact:

- Users comparing runs may see artifact references that are only unique inside
  one run directory.
- Backend implementers may choose incompatible identity policies because the v0
  contract sends mixed signals.

Affected roadmap versions:

- v8 run catalog and comparison;
- v9 run bundles;
- v10 sweeps;
- v12-v13 remote stores;
- v17 cleanup and retention.

Severity: high.

Gate decision: must resolve before v1.

Selected remediation:

- Treat `ArtifactStore` as explicitly run-scoped.
- Remove `run_id` from artifact-store operations and bind store instances to
  one run at construction or runner setup time.
- Keep artifact IDs run-local. Catalogs, bundles, comparisons, and sweep
  summaries should use an explicit `(run_id, artifact_id)` pair when referring
  across runs.

### 3. Runner as a High-Policy Coordinator

Current decision:

- `PipelineRunner` owns run creation/opening, config persistence, provenance
  capture, planning, stage execution, reuse handling, skip handling, failure
  handling, artifact-index updates, and run-result construction.

Why it was reasonable for v0:

- A single serial local runner is easier to reason about.
- The public API is small and demonstrates the full v0 workflow.
- Premature decomposition would have created abstractions before there were
  multiple execution modes.

Long-term limitation:

- Subprocess, SLURM, container, retry, timeout, runtime event, and cleanup
  policies will all need to interact with runner lifecycle.
- The current runner risks becoming the place every future behavior is added.
- It is hard to test or replace one lifecycle concern independently when many
  policies are interleaved.

User impact:

- Bugs in future executor or retry work may affect otherwise unrelated local
  run behavior.
- External tools may have to depend on private runner internals to inspect or
  customize one lifecycle step.

Affected roadmap versions:

- v2 CLI core;
- v3 diagnostics and preflight;
- v4 runtime options;
- v5 subprocess execution;
- v16 reliability policies;
- v17 cleanup and retention.

Severity: high.

Gate decision: must resolve before v1.

Selected remediation:

- Preserve `PipelineRunner` as the public facade.
- Perform a broad pre-v1 internal decomposition around lifecycle/status
  handling, planning invocation, provenance recording, stage coordination,
  artifact commits, failure and blocked-outcome persistence, event emission,
  and lock handling.
- Keep executor-specific behavior out of the runner decomposition; subprocess,
  SLURM, container, retry, and timeout policies remain later roadmap work.

### 4. Planning Policy Concentration

Current decision:

- Planning combines selector normalization, topological ordering, input binding,
  upstream invalidation, fingerprint construction, resume checks, action
  selection, and optional persistence in one path.

Why it was reasonable for v0:

- Planning needed to be deterministic and directly tied to local resume state.
- A single implementation made it easier to prove conservative behavior.

Long-term limitation:

- Selectors, sweeps, retries, runtime options, and CLI explanations may need
  to extend planning without changing resume mechanics.
- Some typing is already loosened around input bindings, which weakens the
  planning contract.
- Future explanation or diff output may be hard to add without increasing
  coupling.

User impact:

- Users may get conservative but opaque behavior as planning grows.
- CLI and preflight features may duplicate planner logic if public explanation
  APIs are not extracted.

Affected roadmap versions:

- v2 CLI core;
- v3 diagnostics and preflight;
- v10 sweeps;
- v16 reliability policies.

Severity: high.

Gate decision: must resolve before v1.

Selected remediation:

- Keep the persisted `ExecutionPlan` model stable as the execution contract.
- Extract typed policy helpers for selector eligibility, upstream invalidation,
  resume checks, action selection, fingerprinting, and diagnostics.
- Add a separate typed `PlanExplanation` or equivalent diagnostics surface for
  CLI and preflight. Do not embed explanation records directly into the
  persisted execution contract, and do not add CLI-local planning logic.

### 5. Shallow Immutability of Core References and Specs

Current decision:

- Value objects such as `ArtifactRef`, `ResourceRef`, `Record`, and `StageSpec`
  are frozen dataclasses, but nested mappings are normalized to mutable `dict`
  values.

Why it was reasonable for v0:

- It keeps construction simple and easy to serialize.
- Tests focus on validation and round-tripping rather than mutation safety.

Long-term limitation:

- A validated or fingerprinted object can be mutated through nested metadata.
- Reproducibility expectations are weaker than the `frozen=True` API suggests.
- Future caches or event records may accidentally observe mutated metadata.

User impact:

- Users may reasonably treat refs and specs as immutable and be surprised by
  mutation through nested dictionaries.
- Downstream tools may need defensive copies around every ref/spec boundary.

Affected roadmap versions:

- v2 CLI JSON output;
- v8 run catalog and comparison;
- v9 run bundles;
- v10 sweeps;
- v12 remote stores;
- v16 runtime events.

Severity: medium.

Gate decision: must resolve before v1.

Selected remediation:

- Make frozen core references, records, and specs recursively immutable at
  construction time.
- Normalize nested mappings and sequences into read-only structures so
  validated, fingerprinted, or persisted objects cannot be mutated through
  nested metadata.
- Continue returning ordinary mutable plain data from `to_dict()` and related
  serialization helpers.

### 6. Persisted Schema Boilerplate and Evolution Cost

Current decision:

- Persisted models use hand-written `to_dict()` / `from_dict()` methods,
  explicit field sets, and strict unknown-field rejection.

Why it was reasonable for v0:

- Strict plain-data schemas make run files inspectable and safe to validate.
- Avoiding a heavy schema framework keeps dependencies and magic low.

Long-term limitation:

- Planning, provenance, status, and failure models are already large.
- Adding schema migrations or compatibility readers will be expensive if every
  model evolves independently.
- Strict unknown-field rejection may make forward/backward compatibility harder
  for run bundles and catalogs.

User impact:

- Users may have difficulty reading older run directories after schema changes
  unless migration policy is designed early.
- Bundle and catalog tools may need many one-off compatibility branches.

Affected roadmap versions:

- v3 diagnostics and preflight;
- v8 run catalog;
- v9 run bundles;
- v16 reliability events;
- v17 cleanup and retention.

Severity: medium.

Gate decision: must resolve before v1.

Selected remediation:

- Keep strict plain-data persisted schemas.
- Add a central schema layer for document version envelopes, unknown-field
  rejection, migration dispatch, compatibility policy, and test helpers.
- Reject unsupported versions and unknown fields by default. Route known older
  versions through explicit migrations rather than broad loose parsing.

### 7. Global Recipe Registry State

Current decision:

- `register_recipe()` mutates a process-global default recipe catalog.
- `compose_config()` also accepts an explicit catalog.

Why it was reasonable for v0:

- It gives projects an easy registration path without plugin discovery.
- It keeps recipe usage simple for Python API callers.

Long-term limitation:

- Process-global state can create hidden behavior in long-lived Python
  processes, test suites, notebooks, and CLI invocations with plugins.
- Plugin discovery later must be careful not to silently mutate global
  registries during import.

User impact:

- Users may see config composition change based on earlier imports or test
  order.
- Reproducibility can depend on process history instead of explicit inputs.

Affected roadmap versions:

- v1 rebuildable config composition;
- v2 CLI core;
- v10 sweeps;
- v11 plugin discovery.

Severity: medium.

Gate decision: must resolve before v1.

Selected remediation:

- Make explicit `RecipeCatalog` construction the reproducible path.
- Keep process-global `register_recipe()` only as a Python convenience for
  scripts and interactive use.
- CLI and plugin workflows must build fresh explicit catalogs from config,
  project, and plugin inputs. They must not depend on process-global registry
  history.

### 8. Run Metadata Naming Ambiguity

Current decision:

- `read_run_metadata()` returns the whole `run.json` wrapper, including
  `schema_version`, `run_id`, `created_at`, `run_dir`, and nested `metadata`.

Why it was reasonable for v0:

- The wrapper is useful and compact.
- Only the local store currently consumes it.

Long-term limitation:

- The method name implies user metadata, not the full run metadata document.
- Future store implementations may copy inconsistent semantics.

User impact:

- Users or CLI code may accidentally treat wrapper fields as user metadata.
- JSON output and run catalog indexing may expose confusing shapes.

Affected roadmap versions:

- v2 CLI core;
- v3 diagnostics;
- v8 run catalog.

Severity: low.

Gate decision: must resolve before v1.

Selected remediation:

- Rename the ambiguous API before v1.
- Use explicit methods such as `read_run_document()` for the whole `run.json`
  wrapper and `read_run_user_metadata()` for the nested user-authored metadata
  value.
- Do not build CLI, diagnostics, or catalog code on top of the ambiguous
  `read_run_metadata()` name.

### 9. Blocked Descendant State Is Not Fully Persisted

Current decision:

- When a stage fails, later planned stages are returned in memory as blocked
  but are not necessarily persisted as stage status records.

Why it was reasonable for v0:

- Resume treats blocked as a planning result rather than a successful persisted
  state.
- V0 focuses on local API results and failure persistence for the failed stage.

Long-term limitation:

- CLI status and run catalog tools that read only persisted files may not see a
  complete run outcome for all planned stages.
- Event streams and reliability policies need durable facts for skipped,
  blocked, retried, and failed stages.

User impact:

- Users inspecting a failed run directory may not immediately know which
  downstream stages were blocked unless they read the plan and infer state.
- Automation may have to reconstruct blocked state repeatedly.

Affected roadmap versions:

- v2 CLI core;
- v3 diagnostics and preflight;
- v8 run catalog;
- v16 runtime events.

Severity: medium.

Gate decision: must resolve before v1.

Selected remediation:

- Persist blocked stage outcome records for every planned descendant of a
  failed stage.
- Distinguish blocked from skipped and failed in the durable status model so
  resume semantics stay conservative.
- Keep the execution plan as the source of planned order, but make run-status
  and catalog-style readers able to report complete stage outcomes without
  re-inferring blocked state.

### 10. Hard Config Dependencies vs Long-Term Dependency Policy

Current decision:

- V0 makes OmegaConf, Pydantic, and PyYAML hard runtime dependencies after config
  composition lands.

Why it was reasonable for v0:

- It avoids supporting multiple install shapes while the public runtime is
  stabilizing.
- Config composition is central to most v0 examples.

Long-term limitation:

- `docs/loom.md` describes a long-term path where primitives can remain
  standard-library-only and config dependencies can be optional extras.
- Users who only need refs, artifacts, serialization, stores, or inspection must
  still install config dependencies.

User impact:

- Lightweight consumers and downstream libraries may avoid depending on `loom`
  primitives because of unnecessary dependency footprint.

Affected roadmap versions:

- v2 CLI core;
- v8 run catalog;
- v9 run bundles;
- v11 plugin discovery.

Severity: medium.

Gate decision: must resolve before v1.

Selected remediation:

- Move OmegaConf, Pydantic, and YAML support behind a `config` optional extra
  before v1.
- Keep primitives, stores, serialization, and inspection paths lightweight and
  importable without config dependencies.
- Keep import-boundary tests strict so optional dependency paths do not leak
  into core runtime imports.

### 11. No-Argument Stage Construction

Current decision:

- Stage specs carry `_target_`, but the local runner imports the target and
  calls it with no constructor kwargs.
- Authored stage `config` is runtime invocation config exposed through
  `StageContext.stage_config`.

Why it was reasonable for v0:

- It gives one stable stage invocation contract.
- It prevents pipeline stage specs from becoming generic object graphs too
  early.
- It keeps config composition separate from execution.

Long-term limitation:

- Some project stages naturally need constructor-injected dependencies, compiled
  helpers, or configured collaborators.
- Users may route all configuration through `StageContext`, even when object
  construction would be cleaner.
- Plugin-discovered stages and subprocess workers may need a clearer stage
  factory contract.

User impact:

- Users must write no-arg wrapper classes or read config inside every stage.
- Reusing already-instantiated objects in tests or notebooks is awkward.

Affected roadmap versions:

- v2 CLI core;
- v5 stage worker and subprocess execution;
- v10 sweeps;
- v11 plugin discovery.

Severity: medium.

Gate decision: must resolve before v1.

Selected remediation:

- Add an explicit stage factory/init contract before v1.
- Standardize authored stage construction as
  `factory: {_target_: ..., init: {...}}`.
- Keep constructor-time kwargs separate from runtime invocation config; authored
  stage `config` remains `StageContext.stage_config`.
- Preserve `run(context, inputs)` as the stage execution contract.
- Fingerprint semantic production inputs only: factory target, factory init
  config, runtime stage config, input artifact refs, selected environment
  identity, and explicit fingerprint fields. Exclude non-semantic operational
  hints by default.

### 12. Runtime, Resource, Event, and Lock Abstractions Are Missing

Current decision:

- V0 rejects authored runtime/retry/when stage fields.
- It has no runtime/resource model, no event model, and no lock manager.

Why it was reasonable for v0:

- Local serial execution does not need those concepts to be correct.
- Rejecting deferred fields avoids silently preserving semantics that do not
  exist.

Long-term limitation:

- Runtime/resource models are prerequisites for subprocess, SLURM, containers,
  preflight, and some reliability policies.
- Event records are prerequisites for observe-only plugins and operational
  monitoring.
- Locking policy may become necessary when CLI, subprocess workers, or
  concurrent controllers can touch the same run.

User impact:

- Early users cannot express executor resources, retries, timeouts, or
  operational hooks in a durable way.
- If users encode these in ad hoc metadata now, later migration may be noisy.

Affected roadmap versions:

- v3 diagnostics and preflight;
- v4 runtime options and resources;
- v5 subprocess execution;
- v6-v7 SLURM;
- v11 plugins;
- v16 reliability policies.

Severity: high.

Gate decision: must resolve before v1.

Selected remediation:

- Define typed runtime/resource, event, and lock foundations before v1.
- Add event models in `loom.pipeline.events`.
- Persist local lifecycle events as append-only strict JSONL with sequence,
  timestamp, scope, event type, and payload.
- Define locking as a store capability; `PipelineRunner` owns acquire/release
  lifecycle around mutating execution.
- Keep unsupported executor, retry, timeout, SLURM, container, and remote-store
  behavior rejected or explicitly unsupported until their roadmap phases.

## Desired Outcome

After all phases land, v0-post should provide:

- Core refs, records, and specs whose frozen API is backed by recursive
  immutability.
- Strict versioned persisted-document helpers. The shared schema layer owns
  envelopes, version checks, unknown-field rejection, and dispatch helpers; each
  document type owns its supported versions and explicit migration table.
- A packaging/import boundary where primitives, stores, serialization, and
  inspection do not require config dependencies.
- Capability-oriented store contracts split across durable state, artifact
  payloads, logs, workspace/temp access, locking, and explicit local-path helper
  protocols.
- A `StageContext` author facade that exposes stage-facing helpers without
  exposing generic run-store or artifact-store internals to project stages.
- A run-scoped artifact-store contract with cross-run references represented by
  `loom.artifacts.ArtifactAddress`.
- Clear run-document and user-metadata read APIs.
- An explicit stage factory contract using
  `factory: {_target_: ..., init: {...}}`, with runtime stage invocation config
  remaining under authored `config`.
- A semantic-only stage fingerprint policy that includes factory target, factory
  init config, runtime stage config, input artifact refs, selected environment
  identity, and explicit fingerprint fields while excluding non-semantic
  operational hints by default.
- Typed runtime/resource, event, lock, and stage-outcome foundations.
- Event models in `loom.pipeline.events`, with local lifecycle events persisted
  as append-only strict JSONL.
- Locking modeled as a store capability, with `PipelineRunner` owning
  acquire/release around mutating execution.
- Planner internals split into typed policy helpers and a separate explanation
  surface.
- `PipelineRunner` preserved as a public facade over smaller lifecycle,
  planning, provenance, artifact, event, and failure/outcome coordinators.
- Explicit recipe catalogs and fresh-catalog composition paths for reproducible
  CLI/plugin workflows.

## Non-Goals

- No remote artifact-store backend, cross-run cache reuse, run catalog, bundle,
  sweep, subprocess, SLURM, container, retry, timeout, or cleanup behavior.
- No CLI feature expansion beyond whatever tests or docs are necessary to keep
  future CLI work from depending on removed contracts.
- No broad rewrite of config composition, I/O codecs, provenance capture, or
  pipeline graph validation beyond the interfaces touched by this plan.
- No move to Pydantic for persisted run/planning/provenance documents.
- No compatibility promise for renamed or removed v0 APIs; breaking changes are
  allowed before v1 when they correct long-term contracts.

## Implementation Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree ownership and dependency direction from
  `docs/structure.md`.
- Keep `PipelineRunner` as the main public execution facade.
- Keep `ExecutionPlan` as the execution contract; expose explanations beside it,
  not by making the execution plan a presentation model.
- Keep local run directories inspectable through ordinary files.
- Keep unsupported future semantics rejected clearly rather than preserving
  fields that look meaningful but have no effect.
- Update `docs/structure.md` and affected feature docs in the phase that creates
  or changes a package boundary or public contract.
- Keep `StageContext` as a stage-author facade. Do not expose generic store
  escape hatches through it.
- Add cross-run artifact identity as `loom.artifacts.ArtifactAddress`; do not
  embed run identity into run-local `ArtifactRef.artifact_id`.
- Persist local runtime events as append-only strict JSONL with sequence,
  timestamp, scope, event type, and payload.
- Model locking as a store capability. The runner owns lock acquire/release
  lifecycle.
- Use explicit per-document schema migration tables rather than a global
  migration registry.
- Fingerprint semantic production inputs only. Do not rerun solely because a
  non-semantic CPU, memory, log, or scheduling hint changed unless a later
  phase explicitly makes that hint semantic.
- Require phase execution plans to record design impact, future compatibility,
  alternatives rejected, debt introduced, reviewability, and suite-level test
  obligations.

## Execution Mode

This plan uses the serial human-merge-gate workflow, not stacked phase PRs.

- Each phase branch starts from updated `develop`.
- Each phase PR targets `develop`.
- Each phase PR requests review from `samcantrill` and mentions
  `@samcantrill` in the PR body or an immediate PR comment.
- Codex does not approve or merge phase PRs. Human review and merge are the
  external gate.
- The managing agent must not start a successor phase while the current phase
  is only `pr_open` or `approved`.
- The managing agent may start the next phase only after the current phase PR
  is verified as `MERGED` into `develop`, updated `develop` has been fetched,
  and this implementation plan records the completed phase as `merged`.
- Each phase execution plan must record this execution mode, the `develop` base
  and target branch, the `samcantrill` review notification, and the approval
  and merge gate state.

## Phased Implementation

Each phase includes an execution context block to speed up the later phase
execution-plan draft/refine passes. These blocks are implementation starting
points, sequencing guidance, closed decisions, and review traps. They do not
replace `docs/phases/` execution plans, and they do not reopen the remediation
choices selected above.

### Phase 1 - Core Contracts, Schemas, And Packaging

Status: merged
Branch: `codex/v0-post-core-contracts`
PR: https://github.com/samcantrill/loom/pull/15

Merge notes:

- Merged into `develop` on 2026-05-04.
- Summary: added recursive plain-data freeze/thaw helpers, made in-scope frozen
  refs/records/manifests/views/specs recursively immutable, added shared
  strict schema helper APIs, migrated selected manifest/status/execution
  failure readers, moved config dependencies behind `loom[config]`, and split
  validation evidence into no-extra and config-extra surfaces.
- Checks: PR-local `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; PR
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package, unit,
  contract, integration, e2e, and config-extra rows; GitHub CI `checks` passed.
- Stack maintenance: root serial phase, no successor branch was started before
  merge, and no retargeting was required.
- Follow-up notes: later persisted document families can adopt the shared
  schema helpers when they change; Phase 2 must continue from updated
  `develop` and must not reopen Phase 1 optional dependency or immutability
  decisions.

Goal:

- Fix the lowest-level contracts before higher layers and tests depend on
  mutable values, one-off schema parsing, or hard config dependency imports.

Scope:

- Make frozen core refs, records, and specs recursively immutable at
  construction time.
- Preserve plain mutable `to_dict()` output for serialization and user
  inspection.
- Add shared persisted-document helpers for schema version envelopes,
  unknown-field rejection, migration dispatch, and compatibility tests.
- Keep migration registration per document type rather than centralizing all
  migrations in global process state.
- Move OmegaConf, Pydantic, and YAML support behind a `config` optional extra.
- Add or update import-boundary tests proving primitives, stores,
  serialization, and inspection paths do not import config dependency paths.
- Update `pyproject.toml`, `Makefile`, the test harness, and suite markers so
  Phase 1 PR evidence covers both default no-extra validation and config-extra
  validation.
- Update `docs/structure.md` and affected serialization/config docs for optional
  dependency and schema-layer ownership changes.

Execution context:

- Start from `src/loom/refs.py`, `src/loom/artifacts.py`,
  `src/loom/records/`, `src/loom/pipeline/specs.py`,
  `src/loom/serialization/schema.py`, `pyproject.toml`, and
  `tests/package/test_import_boundaries.py`.
- First introduce shared freeze/thaw helpers for plain structured data, then
  apply them to frozen public value objects. Keep serialization output mutable
  by thawing at API boundaries rather than exposing internal frozen mappings.
- Treat the current schema-version helpers as seed code. The phase should add a
  small persisted-document API that can reject unknown fields, validate envelope
  versions, and dispatch per-document migrations without a global registry.
- Move config dependencies only after import-boundary tests describe the target
  behavior. Config modules may still require config extras; core, stores,
  serialization, and inspection imports must not.
- Add a reviewable config-extra validation path such as `make
  test-config-extra` or an equivalent `uv run --extra config ...` harness
  target, and include that suite in `make test-summary` evidence. The default
  harness should prove the no-extra import boundary rather than silently
  skipping all config dependency checks.
- Closed decisions: recursive immutability is required, `to_dict()` remains
  mutable, unknown fields are strict errors, and migrations are owned by each
  document family.
- Review focus: watch for `MappingProxyType` or tuple conversions leaking into
  `to_dict()` output, config imports through package `__init__` files, and new
  schema helpers that duplicate existing validation instead of replacing it.

Acceptance criteria:

- Nested metadata/config mappings on core frozen objects cannot be mutated
  after construction.
- Existing serialization round trips still return ordinary plain-data dict/list
  structures.
- Persisted readers reject unsupported schema versions and unknown fields by
  default, while known older versions can route through explicit migrations.
- `import loom` and core primitive/store imports work without config extras.
- Phase 1 validation evidence includes both the default no-extra path and a
  config-extra path, and `make test-summary` makes skipped versus executed
  optional-dependency suites visible.

Design impact:

- This phase makes the public immutability promise true and prevents future
  persisted documents from each inventing their own compatibility policy.

Future compatibility:

- Run bundles, catalogs, event records, and cleanup policies can reuse one
  schema-evolution layer instead of adding ad hoc readers later.

### Phase 2 - Store, Artifact, And Stage Context Capabilities

Status: merged
Branch: `codex/v0-post-store-capabilities`
PR: https://github.com/samcantrill/loom/pull/16

Merge notes:

- Merged into `develop` on 2026-05-04 as squash commit `9c1ec9f`.
- Summary: added `ArtifactAddress`, split run-store capability protocols,
  renamed run-document and user-metadata APIs, made artifact stores explicitly
  run-scoped, narrowed `StageContext` into a stage-author facade with explicit
  local helpers, and updated store, artifact, pipeline, execution, and
  structure docs.
- Checks: PR-local `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  PR-local `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package,
  unit, contract, integration, e2e, and config-extra rows; GitHub checks passed
  on final head `6a3896d`.
- Human merge gate: PR #16 reached `MERGED` on `develop`; Codex did not approve
  or merge the PR. `gh pr edit 16 --add-reviewer samcantrill` was
  rejected by GitHub's Projects Classic GraphQL deprecation path and
  `reviewRequests` remained empty, so the required fallback comment mentioned
  `@samcantrill` at
  https://github.com/samcantrill/loom/pull/16#issuecomment-4369304096.
- Stack maintenance: root serial phase, no successor branch was started before
  merge, and no retargeting was required.
- Follow-up notes: Phase 3 must continue from updated `develop`; concrete
  locking remains Phase 4 work, and remote stores, executors, catalogs, bundles,
  and sweeps remain future-phase work.

Goal:

- Replace generic local path assumptions with backend-neutral capabilities while
  preserving the local store as the inspectable reference implementation.

Scope:

- Break the generic `RunStore` and `StageContext` path-shaped contracts.
- Split store-facing behavior into focused capability protocols for durable
  run-state documents, artifact payloads, logs, workspace/temp access, and
  explicit local-path helpers.
- Reserve the locking capability boundary only where needed for future store
  composition; Phase 4 owns the concrete lock protocol, local implementation,
  docs, and tests.
- Redefine `StageContext` as a narrow stage-author facade with stage config,
  input/output helpers, artifact save/register helpers, and explicitly named
  local workspace helpers where local behavior is intentionally exposed.
- Remove generic `StageContext` access to run-store and artifact-store internals.
- Keep local path access only through explicit local-only helpers or local
  capabilities.
- Make `ArtifactStore` explicitly run-scoped and remove `run_id` from
  artifact-store operations.
- Add `loom.artifacts.ArtifactAddress` as the immutable cross-run
  `(run_id, artifact_id)` value object without embedding run identity into
  run-local artifact IDs.
- Rename ambiguous run-store metadata APIs to clear run-document and
  user-metadata methods.
- Update `docs/structure.md`, `docs/features/artifacts.md`,
  `docs/features/run-store.md`, and `docs/features/pipeline.md` for the new
  ownership boundaries.

Execution context:

- Start from `src/loom/pipeline/stores/run_store.py`,
  `src/loom/pipeline/stores/artifact_store.py`,
  `src/loom/pipeline/stores/local_runs.py`,
  `src/loom/pipeline/stores/local_artifacts.py`,
  `src/loom/pipeline/context.py`, `tests/contracts/test_store_contract.py`,
  and `tests/unit/loom/pipeline/test_context.py`.
- Split capability protocols before rewriting local implementations. The local
  store can satisfy several protocols, but generic protocols must stop requiring
  local `Path` return values.
- Update the local store as the reference implementation, then update callers to
  depend on the narrowest capability they need. Keep explicit local helpers
  available for local-only operations such as inspectable directories, logs, and
  workspace/temp paths.
- Narrow `StageContext` after the store split is usable. The stage-author facade
  should expose stage config, declared output helpers, artifact save/register
  helpers, input helpers, and explicitly named local workspace helpers; it
  should not expose generic run-store or artifact-store objects.
- Add `ArtifactAddress` in `loom.artifacts` as a frozen `(run_id, artifact_id)`
  value for cross-run references. Do not change the meaning of run-local
  `ArtifactRef.artifact_id`.
- Closed decisions: store capabilities are segregated, artifact stores are
  run-scoped, local path access is explicit/local-only, and metadata API names
  must distinguish run documents from user metadata. Concrete locking protocol
  and behavior are out of scope for this phase and owned by Phase 4.
- Review focus: watch for convenience methods that reintroduce generic path
  requirements, project stages retaining store escape hatches, and artifact
  identity changes that make local artifact IDs globally scoped. Also watch for
  premature lock API churn beyond reserving the store capability boundary.

Acceptance criteria:

- Store protocol tests no longer require generic implementations to return
  local `Path` values.
- Local stores still create an ordinary inspectable run directory.
- Local artifact IDs remain human-readable and run-local.
- Catalog/bundle-facing references can carry `ArtifactAddress`.
- No code outside explicit local-store helpers depends on the old
  `read_run_metadata()` semantics.
- Project stages cannot mutate durable run state except through stage-author
  helpers explicitly exposed on `StageContext`.

Design impact:

- This phase is the main public contract break. It prevents v1/v2 users from
  writing against local path assumptions that would block workers, containers,
  clusters, or remote stores.

Future compatibility:

- Remote stores and subprocess workers can implement focused capabilities
  honestly rather than faking local paths.

### Phase 3 - Stage Factory And Semantic Fingerprint Policy

Status: merged
Branch: `codex/v0-post-stage-factory`
PR: https://github.com/samcantrill/loom/pull/17

Merge notes:

- Merged into `develop` on 2026-05-04 as squash commit `0f39e7e`.
- Summary: added explicit `factory` stage construction specs and import-safe
  pipeline-owned target resolution, wired runner construction through the stage
  factory helper, migrated authored stage configs from top-level `_target_`,
  introduced semantic stage fingerprint policy v2 with factory target/init and
  explicit fingerprint fields, treated v1 fingerprints as policy-changed stale
  state, and updated pipeline, execution, fingerprint, and structure docs.
- Checks: PR-local `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  PR-local `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package,
  unit, contract, integration, e2e, and config-extra rows; GitHub checks passed.
- Human merge gate: PR #17 reached `MERGED` on `develop`; Codex did not approve
  or merge the PR. `gh pr edit 17 --add-reviewer samcantrill` was
  rejected by GitHub's Projects Classic GraphQL deprecation path and
  `reviewRequests` remained empty, so the required fallback comment mentioned
  `@samcantrill` at
  https://github.com/samcantrill/loom/pull/17#issuecomment-4370177330.
- Stack maintenance: root serial phase, no successor branch was started before
  merge, and no retargeting was required.
- Follow-up notes: Phase 4 must continue from updated `develop`; concrete
  runtime/resource/event/lock foundations remain Phase 4 work, while planner
  decomposition, runner lifecycle decomposition, catalogs, bundles, sweeps,
  remote stores, and non-local executors remain later phases.

Goal:

- Add stage construction semantics before planner policy is extracted, so
  fingerprints and runner lifecycle work do not build on a soon-to-change
  no-argument construction contract.

Scope:

- Add an explicit authored factory block:

  ```yaml
  factory:
    _target_: project.stages.ExampleStage
    init:
      key: value
  config:
    runtime_key: value
  ```

- Preserve `config` as runtime invocation config exposed through
  `StageContext.stage_config`.
- Preserve `run(context, inputs)` as the stage execution contract.
- Add a stage factory protocol or construction helper that execution can use
  without importing optional config dependency paths.
- Define and implement the semantic-only stage fingerprint policy:
  factory target, factory init config, runtime stage config, input artifact
  refs, selected environment identity, and explicit fingerprint fields are
  semantic; CPU, memory, logging, scheduling, and other operational hints are
  non-semantic by default.
- Update parsing, validation, fingerprint construction, and tests for the split
  between construction config and runtime stage config.
- Update `docs/structure.md`, `docs/features/pipeline.md`,
  `docs/features/execution.md`, and `docs/features/fingerprints.md`.

Execution context:

- Start from `src/loom/pipeline/specs.py`,
  `src/loom/pipeline/execution/runner.py`,
  `src/loom/pipeline/planning/fingerprints.py`,
  `src/loom/pipeline/planning/models.py`,
  `src/loom/config/instantiate/targets.py`, and pipeline config/planning tests.
- Add parsing and value objects for the factory block before changing runner
  construction. Existing `_target_` handling should either migrate to the
  factory shape or remain behind an explicit compatibility path selected in the
  phase execution plan.
- Keep stage construction import-safe for installs without config extras. Target
  import resolution can use a lightweight helper; full config composition and
  recursive object graph instantiation remain optional config behavior.
- Update fingerprints in the same phase as factory parsing so construction
  semantics and reuse semantics cannot drift. The semantic hash input must
  include factory target, factory init, runtime stage config, input artifact
  refs, selected environment identity, and explicit fingerprint fields.
- Closed decisions: `config` is runtime `StageContext.stage_config`,
  `factory.init` is constructor input, `run(context, inputs)` remains the stage
  contract, and operational hints are non-semantic by default.
- Review focus: watch for constructor values being smuggled through
  `stage_config`, runner imports of optional config modules, and fingerprint
  tests that compare only hashes without asserting which fields caused changes.

Acceptance criteria:

- Authored configs can construct stages with `factory._target_` and
  `factory.init` without routing constructor values through
  `StageContext.stage_config`.
- Stage construction remains import-safe for installs without the `config`
  optional extra unless the caller explicitly uses config composition.
- Fingerprint tests prove semantic fields affect reuse and non-semantic
  operational hints do not.
- Existing no-argument stage examples migrate to the factory shape or continue
  through a documented compatibility path chosen by the phase execution plan.

Design impact:

- This phase removes the construction/fingerprint ambiguity before planner
  decomposition, CLI planning, plugin discovery, or worker-side construction
  depends on it.

Future compatibility:

- Plugin-discovered stages and worker-side stage construction can feed the same
  explicit factory contract without relying on import side effects or no-arg
  wrappers.

### Phase 4 - Runtime, Resource, Event, And Lock Foundations

Status: merged
Branch: `codex/v0-post-runtime-events-locks`
PR: https://github.com/samcantrill/loom/pull/18

Merge notes:

- Merged into `develop` on 2026-05-04 as squash commit `cb456cc`.
- Summary: added strict runtime/resource foundation models with local-only
  runtime vocabulary and supported `cpus`, `memory_mb`, `gpus`, and `custom`
  resource fields; rejected deferred executor, retry, timeout, SLURM,
  container, environment, and remote-store semantics; added strict pipeline
  event records and append-only local `events.jsonl`; added backend-neutral
  run event and run lock store capabilities; added strict run lock records and
  conservative local `lock.json` acquire/read/release behavior; added durable
  `StageStatus.BLOCKED` and a status-only blocked lifecycle writer; aligned
  examples, package exports, contracts, and feature docs.
- Checks: PR-local `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed after
  the refinement pass; PR-local `UV_CACHE_DIR=/tmp/uv-cache make test-summary`
  passed with package, unit, contract, integration, e2e, and config-extra rows;
  GitHub checks passed.
- Human merge gate: PR #18 reached `MERGED` on `develop`; Codex did not approve
  or merge the PR. `gh pr edit 18 --add-reviewer samcantrill` was rejected by
  GitHub's Projects Classic GraphQL deprecation path and `reviewRequests`
  remained empty with `samcantrill` as the PR author, so the required fallback
  comment mentioned `@samcantrill` at
  https://github.com/samcantrill/loom/pull/18#issuecomment-4370606278.
- Stack maintenance: root serial phase, no successor branch was started before
  merge, and no retargeting was required.
- Follow-up notes: Phase 5 must continue from updated `develop`; planner policy
  decomposition remains Phase 5 work, while runner lifecycle decomposition,
  catalogs, bundles, sweeps, remote stores, and non-local executors remain
  later phases.

Goal:

- Add the durable state vocabulary that later runner and CLI work can depend on
  without implementing deferred executor/retry policies early.

Scope:

- Add typed runtime/resource foundation models that validate supported local
  v0 fields and reject unsupported executor, retry, timeout, SLURM, container,
  and remote-store semantics.
- Add event models in `loom.pipeline.events`.
- Persist local event records as append-only strict JSONL with sequence,
  timestamp, scope, event type, and payload.
- Define locking as a store capability, with a conservative local
  implementation. This phase owns the concrete lock protocol, local
  implementation, serialization/status documentation, and unit/contract tests.
- Add durable stage-outcome/status support for blocked descendants, distinct
  from skipped and failed.
- Wire local store persistence for event JSONL, lock, and blocked-outcome
  document shapes where the store layer owns those files.
- Update `docs/structure.md`, `docs/features/runtime-resources.md`,
  `docs/features/state.md`, `docs/features/run-store.md`, and
  `docs/features/reliability.md`.

Execution context:

- Start from `src/loom/pipeline/status.py`,
  `src/loom/pipeline/stores/local_runs.py`,
  `src/loom/pipeline/execution/lifecycle.py`,
  `src/loom/pipeline/execution/models.py`, runtime/resource feature docs, and
  local execution failure tests.
- Add foundation models before broad runner wiring. This phase should make
  runtime/resource/event/lock/outcome records serializable and locally
  persistable; Phase 7 owns full runner lifecycle integration.
- Put event types in `loom.pipeline.events`, not in execution internals. Local
  event persistence should be strict append-only JSONL with versioned records,
  monotonic per-run sequence, timestamp, scope, event type, and plain-data
  payload.
- Model locks as a store capability. The local implementation should prevent
  obvious same-run concurrent writers but should not claim distributed locking,
  stale-lock cleanup, or remote-store semantics.
- Do not revisit the Phase 2 store split except where needed to add the
  concrete lock capability reserved there.
- Add durable blocked outcome/status support in a way that preserves the
  distinction between skipped, failed, stale, and blocked. Persisting a blocked
  outcome should not require executing the blocked stage.
- Closed decisions: unsupported executor/retry/timeout/container/SLURM fields
  are rejected, events live under `loom.pipeline.events`, JSONL is append-only,
  and locking belongs to store capabilities.
- Review focus: watch for event emission mixed into runner control flow too
  early, lock APIs that require local paths generically, and blocked state that
  only appears in in-memory `RunResult`.

Acceptance criteria:

- Unsupported runtime/retry/timeout/executor fields fail clearly and do not
  appear as silently honored metadata.
- Event record serialization is strict, versioned, inspectable, and append-only
  in the local store.
- Local lock behavior prevents obvious same-run concurrent writers without
  requiring distributed locking.
- Blocked stage outcomes can be written and read without executing downstream
  stages.

Design impact:

- This phase gives later runner decomposition a stable vocabulary for lifecycle
  facts, instead of adding events and blocked status as incidental runner
  side effects.

Future compatibility:

- Plugins can later observe event records, and reliability policies can later
  extend the same event/outcome vocabulary.

### Phase 5 - Planner Policy Decomposition And Explanations

Status: merged
Branch: `codex/v0-post-planner-policy`
PR: https://github.com/samcantrill/loom/pull/19

Merge notes:

- Merged into `develop` on 2026-05-04 as squash commit `496cba8`.
- Summary: extracted planner invalidation and action-decision policy into typed
  helper modules, rewired `planner.py` around `ResolvedInputBinding` without
  changing execution-plan persistence, added `PlanExplanation` and
  `StageExplanation` diagnostics derived from `ExecutionPlan`, tightened
  explanation parsing, preserved semantic fingerprint policy/version, updated
  public planning exports, and aligned structure, graph, resume, preflight, and
  fingerprint docs.
- Checks: PR-local `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed after
  the refinement pass; PR-local `UV_CACHE_DIR=/tmp/uv-cache make test-summary`
  passed with package, unit, contract, integration, e2e, and config-extra rows;
  GitHub checks passed.
- Human merge gate: PR #19 reached `MERGED` on `develop`; Codex did not approve
  or merge the PR. `gh pr edit 19 --add-reviewer samcantrill` was rejected by
  GitHub's Projects Classic GraphQL deprecation path and `reviewRequests`
  remained empty with `samcantrill` as the PR author, so the required fallback
  comment mentioned `@samcantrill` at
  https://github.com/samcantrill/loom/pull/19#issuecomment-4370912666.
- Stack maintenance: root serial phase, no successor branch was started before
  merge, and no retargeting was required.
- Follow-up notes: Phase 6 must continue from updated `develop`; explicit
  recipe catalogs and fresh composition remain Phase 6 work, while runner
  lifecycle decomposition, non-local executors, remote stores, bundles, sweeps,
  and final migration notes remain later phases.

Goal:

- Keep planning deterministic while making selector, invalidation, resume,
  fingerprint, action, and explanation policy testable independently.

Scope:

- Extract typed planner helpers for selector eligibility, upstream
  invalidation, resume checks, action selection, fingerprinting, and diagnostic
  construction.
- Keep `ExecutionPlan` as the persisted execution contract.
- Add a separate typed `PlanExplanation` or equivalent diagnostic surface for
  CLI/preflight consumers.
- Preserve the semantic-only fingerprint policy defined in Phase 3.
- Remove or tighten loosened typing around input bindings where the current
  planner path has type erosion.
- Update `docs/structure.md`, `docs/features/pipeline-graph.md`,
  `docs/features/resume.md`, `docs/features/preflight.md`, and
  `docs/features/fingerprints.md`.

Execution context:

- Start from `src/loom/pipeline/planning/planner.py`,
  `src/loom/pipeline/planning/models.py`,
  `src/loom/pipeline/planning/resume.py`,
  `src/loom/pipeline/planning/selectors.py`,
  `src/loom/pipeline/planning/fingerprints.py`, and planner/resume tests.
- Extract helpers around existing behavior before changing model shapes. A good
  order is selector eligibility, input binding and upstream invalidation, resume
  checks, action selection, fingerprint assembly calls, then diagnostics.
- Keep `ExecutionPlan` as the persisted execution record. Add
  `PlanExplanation` beside it for CLI/preflight diagnostics instead of turning
  plan files into presentation envelopes.
- Preserve Phase 3 fingerprint semantics exactly. This phase may move
  fingerprint policy calls behind helpers, but it must not change which inputs
  are semantic.
- Tighten types where the planner currently passes generic objects through
  stage plans, especially around bound inputs, pending inputs, and plan reasons.
- Closed decisions: planning remains deterministic, explanations are separate
  from execution records, and CLI/preflight must call planner policy helpers
  rather than duplicate planning logic.
- Review focus: watch for behavior changes hidden inside refactors, explanation
  models that become required to execute a plan, and tests that assert private
  helper structure instead of public planning outcomes.

Acceptance criteria:

- Existing planning and resume behavior is preserved.
- Explanation tests can inspect action reasons and invalidation causes without
  parsing CLI text or private planner internals.
- CLI-facing planning helpers do not duplicate planning, resume, or selector
  semantics.
- `ExecutionPlan` files remain stable execution records, not presentation
  envelopes.

Design impact:

- This phase turns planning from one large policy path into composable policy
  units without changing the persisted execution contract.

Future compatibility:

- CLI `plan`, diagnostics/preflight, sweeps, and reliability work can reuse the
  same explanation and policy helpers.

### Phase 6 - Explicit Recipe Catalogs And Fresh Composition

Status: in_progress
Branch: `codex/v0-post-recipe-catalogs`
PR: pending

Goal:

- Make reproducible config composition explicit and remove process-history
  surprises before CLI, plugins, and sweeps build on composition behavior.

Scope:

- Make explicit `RecipeCatalog` construction the reproducible path in public
  docs and code used by run/config composition.
- Keep process-global `register_recipe()` only as a Python convenience for
  scripts and interactive use.
- Add a fresh-catalog composition path suitable for future CLI and plugin
  workflows so process-global registry history is ignored there.
- Keep plugin discovery itself deferred.
- Update `docs/structure.md`, `docs/features/config.md`, and
  `docs/features/plugins.md` for catalog ownership and global-state policy.

Execution context:

- Start from `src/loom/config/api.py`,
  `src/loom/config/compose.py`,
  `src/loom/config/recipes/catalog.py`,
  `src/loom/config/recipes/expansion.py`, recipe contract tests, and config
  composition tests.
- Make explicit `RecipeCatalog` construction the documented reproducible path
  before changing composition defaults. Composition APIs used by future CLI and
  plugin code should be able to receive or create a fresh catalog explicitly.
- Keep process-global `register_recipe()` as a convenience for Python scripts,
  notebooks, and interactive use. It should not be the path future CLI/plugin
  workflows use for reproducible composition.
- Add tests that register recipes globally and then prove fresh-catalog
  composition ignores that process history. Keep plugin discovery deferred to a
  later roadmap phase.
- Closed decisions: explicit catalogs are the reproducible path, global
  registration remains convenience-only, and plugin discovery is out of scope.
- Review focus: watch for tests that depend on process-global cleanup order,
  composition helpers that silently fall back to global state, and docs that
  imply plugin entry-point loading exists in this phase.

Acceptance criteria:

- Reproducible composition tests pass with explicit catalogs and do not observe
  prior global registration.
- Interactive/script registration remains available where explicitly documented.
- CLI/plugin-oriented composition helpers construct fresh explicit catalogs and
  do not depend on global registry history.

Design impact:

- This phase removes hidden global/process-history risks before CLI, plugins,
  sweeps, and workers make composition more visible.

Future compatibility:

- Plugin-discovered recipes can feed explicit catalogs without relying on
  import side effects.

### Phase 7 - Runner Lifecycle Decomposition

Status: pending
Branch: `codex/v0-post-runner-lifecycle`
PR: pending

Goal:

- Preserve `PipelineRunner` as the public facade while splitting lifecycle
  concerns into smaller internal coordinators.

Scope:

- Split runner internals around run creation/opening, lock acquire/release,
  planning invocation, provenance recording, stage coordination, artifact
  commits, event emission, failure recording, blocked-outcome persistence, and
  result construction.
- Update local execution to use the stage-author context facade, run-scoped
  artifact store, explicit stage factory, event/outcome foundations, and store
  lock capability.
- Persist blocked descendant outcomes after a failed stage.
- Emit local run/stage lifecycle events for planned, started, completed,
  failed, skipped, reused, and blocked outcomes where applicable.
- Keep executor-specific subprocess, SLURM, container, retry, and timeout
  behavior out of this phase.
- Update `docs/structure.md`, `docs/features/execution.md`,
  `docs/features/state.md`, and `docs/features/reliability.md`.

Execution context:

- Start from `src/loom/pipeline/execution/runner.py`,
  `src/loom/pipeline/execution/lifecycle.py`,
  `src/loom/pipeline/executors/base.py`,
  `src/loom/pipeline/executors/local.py`,
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_local_execution_resume.py`, and
  `tests/integration/pipeline/test_local_execution_failures.py`.
- Decompose around already-established contracts from Phases 2 through 5. Do
  not start this phase by inventing replacement public APIs; `PipelineRunner`
  remains the public facade and the new components are internal lifecycle
  collaborators.
- A safe extraction order is run creation/opening and status transitions,
  planning invocation, stage context construction, stage execution coordination,
  artifact/index commits, failure and blocked-outcome persistence, event
  emission, and final result construction.
- Acquire and release the store lock around mutating run execution. Ensure
  failure paths release locks and emit/persist the same lifecycle facts as
  success paths where applicable.
- Persist blocked descendant outcomes after the first failed stage and emit
  lifecycle events for planned, started, completed, failed, skipped, reused, and
  blocked outcomes. Do not add subprocess, SLURM, container, retry, timeout, or
  cleanup behavior.
- Closed decisions: runner decomposition is internal, stage execution uses the
  stage-author context facade, artifact stores are run-scoped, stage factories
  are explicit, and event/lock/outcome foundations from Phase 4 are reused.
- Review focus: watch for future executor policy leaking in, lifecycle helpers
  that still require full synthetic pipelines for unit tests, missing lock
  release on exceptions, and blocked outcomes that are returned but not
  persisted.

Acceptance criteria:

- Success, failure, skip, reuse, and blocked-result integration tests still pass
  through `PipelineRunner`.
- Failed runs persist complete downstream blocked outcomes.
- Local event records are written deterministically enough for tests and human
  inspection.
- Local run locking is acquired and released around mutating run execution.
- Runner unit tests can target lifecycle subcomponents without constructing an
  entire synthetic pipeline for every concern.

Design impact:

- This phase removes the highest-maintenance pressure point while retaining the
  small public execution facade.

Future compatibility:

- Later subprocess, SLURM, container, retry, timeout, event-sink, and cleanup
  work can attach to lifecycle boundaries instead of modifying one monolithic
  runner.

### Phase 8 - Hardening, Docs, And Migration Notes

Status: pending
Branch: `codex/v0-post-hardening-docs`
PR: pending

Goal:

- Close the pre-v1 hardening work with migration notes, end-to-end coverage,
  roadmap alignment, and a final documentation consistency pass.

Scope:

- Verify that `docs/loom.md`, `docs/structure.md`, and affected feature docs
  already reflect the phase-local contract changes.
- Add migration notes for renamed/removed v0 APIs and expected user-facing
  changes.
- Update downstream implementation plans so v1 starts after this hardening
  sequence and does not repeat superseded assumptions.
- Add focused end-to-end tests for local run success, failure with blocked
  outcomes, resume/reuse, explicit catalog composition, stage factory
  construction, and local event/lock behavior.
- Run final validation gates and record suite-level evidence.

Execution context:

- Start from `docs/loom.md`, `docs/structure.md`, affected `docs/features/`
  files, `tests/e2e/test_local_pipeline_run.py`, integration pipeline tests,
  and the package/import test suite.
- Treat this phase as a closeout pass, not a dumping ground for contract docs
  that earlier phases should have updated. If a public contract changed in an
  earlier phase, its docs should already be updated by that phase.
- Add migration notes that map removed or renamed v0 APIs to replacement APIs,
  including local path helpers, run metadata naming, artifact-store run scoping,
  `ArtifactAddress`, stage factory blocks, stage context access, and recipe
  catalog behavior.
- Add or refresh focused e2e coverage only for the corrected v0-post local
  behavior. Keep remote stores, non-local executors, retries, timeouts, plugin
  discovery, sweeps, catalogs, bundles, and cleanup explicitly deferred.
- Run `make validate-pr` and `make test-summary` during PR preparation and
  record suite-level evidence in the phase PR body.
- Closed decisions: this phase verifies and documents the completed hardening
  sequence; it does not reopen architecture choices or introduce new runtime
  features.
- Review focus: watch for docs that describe deferred features as implemented,
  migration notes that omit breaking public changes, and e2e tests that depend
  on implementation internals instead of public APIs.

Acceptance criteria:

- Docs describe only supported pre-v1 behavior and explicitly defer remote
  stores, non-local executors, retries, timeouts, plugin discovery, sweeps,
  catalogs, bundles, and cleanup behavior.
- Migration notes identify breaking API changes and replacement APIs.
- `make validate-pr` passes.
- `make test-summary` records suite-level evidence.
- The implementation plan status can move to complete only after all earlier
  phases are merged.

Design impact:

- This phase makes the hardening visible and reviewable for users before v1
  config composition resumes without delaying structure updates until the end.

Future compatibility:

- Later roadmap phases start from corrected contracts and do not need to
  explain around v0-local debt.

## Overall Test Plan

Package and import tests:

- `import loom` remains cheap.
- Primitive, schema, serialization, store, and inspection imports do not require
  config extras.
- Config APIs fail clearly when config extras are not installed.
- Phase 1 establishes a config-extra validation target and suite-summary entry
  so optional-dependency behavior is tested with the extra installed rather than
  hidden behind default-suite skips.

Unit tests:

- Recursive immutability and mutable `to_dict()` output.
- Schema version envelopes, unknown-field rejection, and per-document migration
  dispatch tables.
- Segregated store capability contracts and the stage-author `StageContext`
  facade.
- Run-scoped artifact store behavior and `ArtifactAddress` references.
- Stage factory parsing, construction, import-safe target resolution, and
  semantic-only fingerprint behavior.
- Runtime/resource model validation, append-only event JSONL serialization,
  lock capability behavior, and blocked outcome serialization.
- Planner policy helpers and separate explanation records that preserve the
  semantic fingerprint contract.
- Explicit recipe catalogs and fresh composition paths.

Integration tests:

- Local pipeline success through `PipelineRunner`.
- Failed local pipeline with durable failed and blocked outcomes.
- Resume/reuse behavior after contract changes.
- Local event records and lock behavior during runner execution.
- Stage factory construction with separate runtime `stage_config`.
- Explicit catalog composition that is unaffected by prior process-global
  recipe registration.

Validation gates:

- Run narrower package tests during each phase as needed.
- Phase 1 must produce reviewable evidence for both default no-extra validation
  and config-extra validation, and later phases must preserve those suite
  targets when touching config imports or package metadata.
- Run `make validate-pr` before each phase PR.
- Run `make test-summary` during PR preparation so suite evidence is available.

## Maintainability Assessment

The selected plan is intentionally front-loaded. It fixes foundational contracts
before v1 and v2 expand public usage through config composition and CLI
commands. The main maintainability risk is phase size: store/context
capabilities, stage factory/fingerprint policy, runtime events/locks, and runner
lifecycle decomposition are each large enough to require their own phase
execution plans and should not be collapsed into one PR.

The plan reduces long-term maintenance risk by:

- moving schema evolution into one shared layer;
- making immutable public value objects actually immutable;
- preventing local path assumptions from spreading through user stages and CLI
  code;
- separating stage author APIs from backend/store APIs;
- resolving stage construction and semantic fingerprinting before planner
  decomposition;
- keeping event models in a pipeline-level package instead of execution
  internals;
- keeping planner explanations out of CLI-local logic; and
- splitting runner lifecycle behavior before more executor modes arrive.

## Extensibility Assessment

The plan keeps `loom` domain-neutral while opening the expected roadmap paths:

- Remote stores can implement capabilities without pretending to be local
  filesystems.
- Catalogs, bundles, and sweeps can use `ArtifactAddress` without changing
  run-local artifact IDs.
- Project stages can remain portable because `StageContext` exposes stage-author
  helpers instead of store internals.
- Plugins can later load recipes into explicit catalogs and observe event
  records without relying on import side effects.
- Subprocess, SLURM, and container executors can attach to runner lifecycle and
  runtime/resource foundations without changing stage invocation semantics.

Deferred extensibility remains intentional for remote payload operations,
distributed locks, real plugin discovery, retry/timeout policy, sweep
orchestration, catalog storage, and non-local executor implementations.

## Technical Debt Ledger

- Breaking pre-v1 APIs are accepted to correct local path, metadata naming,
  artifact-store, and stage-construction contracts. Revisit only if downstream
  users require a compatibility bridge before v1.
- Local path helpers remain accepted debt on explicit local-only types. Revisit
  if they leak into generic protocols or public examples.
- The serial human-merge-gate workflow is accepted to avoid stacked-PR
  maintenance complexity. Revisit only if phase review latency blocks progress
  enough to justify a shallow stack.
- The no-extra/config-extra split introduces two validation surfaces. Revisit if
  `make test-summary` no longer makes skipped optional-dependency suites
  visible or config-extra validation drifts out of PR evidence.
- Strict unknown-field rejection is accepted for inspectability. Revisit when
  run bundles or catalogs need forward-tolerant partial inspection.
- Per-document migration tables are accepted over a global migration registry.
  Revisit if many document families need shared cross-document migration
  orchestration.
- Global recipe registration remains accepted as a Python convenience. Revisit
  if tests, notebooks, or plugin work show process-history surprises despite
  explicit-catalog paths.
- Local lock behavior is intentionally conservative and not distributed.
  Revisit when subprocess workers, SLURM operations, or remote stores introduce
  real concurrent controllers.
- Locking is reserved as a store capability boundary before its concrete API is
  added. Revisit if Phase 2 leaks a partial lock protocol or if Phase 4 needs to
  undo earlier store capability decisions.
- Semantic-only fingerprinting intentionally excludes non-semantic operational
  hints. Revisit if users need a declared runtime hint to affect reuse.
- Runtime/resource models are foundation-only in this plan. Retry, timeout,
  executor, scheduler, and container semantics remain deferred.

## Plan Quality Gate

Status: passed.

Before any phase implementation starts, this plan must pass the project plan
quality gate for maintainability, extensibility, future compatibility,
conflicting design choices, technical debt, test strategy, and reviewability.

Budget state:

- Initial plan review: used.
- Automated plan refinement pass: used.
- Confirmation review: used.

Gate requirements:

- A reviewer must confirm that the eight-phase sequence is reviewable and does
  not hide future executor, remote-store, plugin, sweep, retry, timeout, or
  catalog work inside pre-v1 hardening.
- A reviewer must confirm that serial human-merge-gate mode is recorded as a
  durable plan constraint and each phase execution plan must branch from
  updated `develop`, target `develop`, request/record `samcantrill` review,
  wait for human approval and merge, and avoid successor implementation until
  the current phase is `merged`.
- A reviewer must confirm that Phase 1 defines reviewable no-extra and
  config-extra validation evidence through `pyproject.toml`, the Makefile/test
  harness, suite markers, and `make test-summary`.
- A reviewer must confirm that Phase 2 only reserves the store lock capability
  boundary, Phase 4 owns the concrete lock protocol and local tests/docs, and
  Phase 7 only integrates the established lock capability into runner
  lifecycle.
- A reviewer must confirm that each phase updates `docs/structure.md` and
  affected feature docs when it changes package ownership or public contracts.
- A reviewer must confirm that the stage-author context facade, segregated store
  capabilities, `ArtifactAddress`, event JSONL, store-capability locking,
  semantic fingerprint policy, and explicit recipe catalog decisions are not
  reopened by phase execution plans.
- Any accepted risk must remain recorded in the technical debt ledger with a
  concrete revisit trigger.
- Each phase execution plan must preserve the selected remediation choices from
  this document and must not re-open them without explicit user instruction.

## Pre-V1 Gate Assessment

V1 config composition should not proceed until all phases in this plan land.
The highest-risk v0 decisions do not directly concern `_include_`, `_replace_`,
`_copy_`, source snapshots, or config fingerprints, but v1 would make config,
stage, runner, and store contracts more visible. Those contracts should be
corrected first.

Selected gate outcome:

```text
Create and implement the dedicated v0-post hardening sequence before v1.
Breaking API changes are allowed before v1 where they fix long-term contracts.
After hardening lands, v1 config composition may proceed on top of the corrected
store, context, planner, runner, schema, catalog, and dependency boundaries.
```
