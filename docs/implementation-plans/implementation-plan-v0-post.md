# V0 Post-Implementation Architecture Limitations Audit

## Goal

Evaluate the current v0 implementation against the longer-term `loom` vision in
[`docs/loom.md`](../loom.md), [`docs/structure.md`](../structure.md), and the
post-v0 roadmap.

This is a pre-v1 architecture gate audit, not an implementation plan for fixes.
It records decisions that were reasonable for the local v0 runtime but may
limit future users or roadmap work if they harden into permanent contracts.

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
- gate decision.

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

Gate decision: must resolve before v1 if v1 or v2 documents additional public
usage of run paths; otherwise resolve before v4 at the latest.

Recommended direction:

- Separate durable run-state persistence from local layout/path allocation.
- Introduce capability-oriented store methods before non-local execution relies
  on current `Path` returns.
- Keep local path helpers for `LocalRunStore`, but avoid making them the only
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

Gate decision: resolve before later roadmap step, ideally before v8.

Recommended direction:

- Decide explicitly whether `ArtifactStore` is run-scoped or multi-run.
- If multi-run, include `run_id` in managed artifact identity and path/URI
  allocation policy.
- If run-scoped, remove `run_id` from the artifact-store contract and let the
  runner bind a store instance to a run.

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

Gate decision: resolve before later roadmap step, before v5 at the latest.

Recommended direction:

- Preserve `PipelineRunner` as the public facade.
- Split internals around lifecycle/status, provenance recording, stage
  coordination, artifact commits, and failure recording before adding multiple
  executor modes.

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

Gate decision: resolve before later roadmap step, preferably before v2 exposes
planner explanations widely.

Recommended direction:

- Keep the persisted `ExecutionPlan` model stable.
- Extract typed policy helpers for selector eligibility, upstream invalidation,
  direct resume checks, and plan explanation.
- Avoid CLI-local planning logic.

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

Gate decision: resolve before later roadmap step.

Recommended direction:

- Decide whether refs/specs are deeply immutable or explicitly mutable
  snapshots.
- If immutable, normalize nested mappings and lists into read-only structures
  or copy deeply at all persistence/fingerprint boundaries.

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

Gate decision: resolve before later roadmap step.

Recommended direction:

- Keep strict persisted schemas, but centralize document version checks,
  migration hooks, and compatibility policy.
- Avoid adding many more persisted shapes before defining schema evolution
  rules.

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

Gate decision: monitor for v1, resolve before v11.

Recommended direction:

- Prefer explicit catalog construction for reproducible runs.
- If global registration remains, document reset/inspection behavior and
  plugin-loading boundaries.

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

Gate decision: monitor; rename or add a clearer method before broad CLI/catalog
exposure.

Recommended direction:

- Add explicit names such as `read_run_document()` and `read_run_user_metadata()`
  if both shapes are needed.

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

Gate decision: resolve before later roadmap step, ideally before v3.

Recommended direction:

- Decide whether blocked remains plan-only or receives a persisted stage
  outcome document.
- If persisted, distinguish blocked from skipped and failed so resume semantics
  stay conservative.

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

Gate decision: monitor; revisit before packaging or plugin work makes this
harder to reverse.

Recommended direction:

- Keep import-boundary tests strict.
- Reassess optional extras after v0 and before promoting primitives as a
  lightweight library surface.

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

Gate decision: monitor for v1/v2; resolve before stage-worker or plugin work if
real users hit the no-arg constraint.

Recommended direction:

- Preserve `run(context, inputs)` as the stage execution contract.
- Consider an explicit stage factory or stage object adapter only after a real
  downstream need appears.

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

Gate decision: resolve before later roadmap step, before v4.

Recommended direction:

- Keep v0 rejection behavior.
- Define typed runtime/resource objects before executor-specific implementations.
- Define runtime event records before plugin event sinks.
- Add locks only after CLI or worker modes create a concrete concurrent-access
  risk.

## Pre-V1 Gate Assessment

V1 config composition can proceed if it avoids broadening the public surface of
local path-shaped run/store APIs. The highest-risk v0 decisions do not directly
block `_include_`, `_replace_`, `_copy_`, source snapshots, or config
fingerprints.

However, v2 and later roadmap work should not build more user-facing behavior
on top of unclear store, artifact identity, planner explanation, or runner
lifecycle boundaries without a follow-up architecture plan.

Recommended gate outcome:

```text
v1 may proceed with caution.
Before v2 exposes CLI plan/run behavior broadly, review planner explanations,
run metadata naming, and blocked descendant visibility.
Before v4/v5, resolve local path-shaped store/context contracts and runner
internal lifecycle boundaries.
Before v8/v12, resolve artifact store run scope and artifact identity.
```

## User Impact Summary

Current v0 users get a clear and useful local runtime, but the documented
limitations affect how safely those users can grow:

- Users should treat v0 stages as local-first unless they only use
  `StageContext.save_artifact()` / `register_artifact()` and avoid direct path
  assumptions.
- Users should assume artifact IDs are run-local, not global.
- Users should prefer explicit recipe catalogs in reproducible contexts.
- Users should not encode future runtime, resource, retry, or event semantics in
  arbitrary metadata and expect `loom` to honor them later.
- Users should expect v0 persisted schemas to be strict and inspectable, but not
  yet backed by a full migration story.

## Audit Conclusion

No finding shows a domain-neutrality failure or a need to discard the v0
architecture. The central package boundaries are sound: config, serialization,
I/O, pipeline planning, stores, execution, provenance, and CLI responsibilities
remain distinct in the design.

The critical risk is that v0-local conveniences become public contracts before
the roadmap adds non-local execution, runtime options, remote stores, catalogs,
and events. The next architecture work should therefore focus on capability
boundaries, not broad rewrites.

Highest-priority follow-up topics:

1. Store and `StageContext` capability boundary.
2. Artifact-store run scope and artifact identity.
3. Runner internal lifecycle decomposition.
4. Planner explanation and policy decomposition.
5. Persisted schema evolution policy.
