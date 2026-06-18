# Implementation Plan v4: Runtime Options And Resources

## Metadata

- Status: refined implementation plan
- Related planning notes:
  `docs/roadmap/stage-4/planning.md`
- Related brief: none
- Related specifications:
  - `docs/features/runtime-resources.md`
  - `docs/features/execution.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/pipeline.md`
  - `docs/features/testing.md`
- Draft pass: complete on 2026-05-07
- Refine pass: complete on 2026-05-07 after local review for future-roadmap
  compatibility
- Plan quality gate: passed on 2026-05-07 after initial
  `loom_plan_reviewer` review, one refinement pass, and confirmation review
- Blockers: none known

## Goal

Implement `loom` v4 as the shared runtime-options and resources layer used by
local preflight, CLI/config mapping, run planning, local execution metadata, and
future subprocess, SLURM, container, sweep, plugin, and reliability work.

The v4 target is a stable public Python control surface for how a specific
invocation should run, without mixing operational choices into semantic
pipeline specs.

## Context

The roadmap defines v4 as "Runtime options and resources":

- Typed invocation, resume, execution, profile, and resource models.
- Normalization and validation for executor names, dry-run flags, resume
  settings, selector fields, tags, notes, and scheduler-neutral resource
  requests.
- Config and CLI mapping into runtime option objects.
- Capability-aware validation for resource fields without executor-specific
  assumptions in the core resource model.
- An executor registry surface for resolving known executor names without
  loading optional backends eagerly.
- Preflight checks for runtime option consistency and unsupported executor
  capability declarations.
- Tests for normalization, validation, serialization, CLI/config mapping, and
  resource edge cases.

V0 through v3 provide the runtime foundation this plan builds on: local pipeline
specs, planning, resume, local execution, local run/artifact stores, config
composition, CLI validate/plan/run, and diagnostics/preflight. Current source
state includes `src/loom/pipeline/resources.py` with
`ResourceRequest(cpus, memory_mb, gpus, custom)` and
`src/loom/pipeline/runtime.py` with a local-only `RuntimeRequest`. V4
intentionally replaces the resource model with a typed-entry schema and expands
runtime options while preserving existing planning, execution, store, config,
diagnostics, and CLI ownership boundaries.

## Desired Outcome

After v4 is complete:

- Public Python callers can construct, normalize, validate, serialize, and pass
  `RunOptions` through Loom workflows.
- `RunOptions` is the single canonical invocation-policy model: CLI, config,
  Python API, runner, and executor-facing stage requests must not maintain
  parallel interpretations of run URI, selectors, resume, tags, notes,
  dry-run, executor, resources, stage options, environment requests, or adapter
  options.
- Config `runtime` / `runtime_profiles` sections and CLI flags map into the
  same normalized runtime option objects as programmatic API calls.
- Per-stage runtime options are first-class runtime/profile data resolved by
  exact stage ID after pipeline construction.
- The run workflow can compute resolved per-stage runtime handoff data that
  future stage-worker and executor phases can consume without reinterpreting raw
  config/profile merge rules, while persisted metadata remains a safe summary.
- The existing execution `RunRequest` remains the runner envelope for config,
  pipeline, provenance, stores, and lifecycle inputs, but it carries normalized
  `RunOptions` as its canonical invocation-policy field.
- Resource requests use typed entries, such as `cpu`, `memory`, and `gpu`,
  rather than durable top-level CPU/memory/GPU fields.
- Executor descriptors provide structured capability metadata without eager
  optional backend imports.
- Preflight reports runtime/profile/stage/executor/resource capability issues
  with stable check IDs.
- Local runs persist safe runtime metadata in a separate schema-versioned
  `runtime.json` record.
- Runtime options, profiles, resources, environment, tags, notes, and adapter
  options remain excluded from semantic fingerprints by default.
- All default tests remain local and domain-neutral, with no requirement for
  real SLURM, Docker, Apptainer, network, or plugin discovery.

## Non-Goals

- No stage-worker execution or subprocess process control.
- No worker process consumes resolved per-stage runtime records in v4.
- No SLURM script generation or live scheduler operations.
- No Docker, Apptainer, or container command construction.
- No retry policy, timeout enforcement, failure categorization, or
  wall-time semantics.
- No parallel local scheduling.
- No remote stores, sweeps, run catalogs, run bundles, cleanup, retention, or
  dashboards.
- No plugin discovery or entry point loading.
- No SLURM, Docker, Apptainer, retry, timeout, remote-store, or sweep-specific
  option interpretation.
- No glob, tag, group, or pattern-based per-stage runtime override matching.
- No local in-process environment application.
- No environment key or value persistence.
- No compatibility aliases for the old `cpus`, `memory_mb`, or `gpus`
  resource fields.

## Constraints

- Preserve `loom` as a domain-neutral runtime.
- Preserve the import boundaries in `docs/structure.md`.
- Keep CLI as an outer presentation layer; lower-level runtime, planning,
  execution, stores, config, and diagnostics modules must not import
  `loom.cli`.
- Keep runtime models import-light and avoid eager loading of optional executor
  backends.
- Treat authored configs as trusted project code.
- Prefer standard-library runtime model implementation and existing local helper
  APIs.
- Avoid new heavyweight runtime dependencies.
- Use `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.
- Do not start phase execution until the plan quality gate passes.

## Design Principles

- Public Python API stability and design quality come before CLI argument
  convenience.
- Runtime options describe how this invocation should run; pipeline specs
  describe what work exists.
- Planning owns selector, resume, invalidation, and stage eligibility
  semantics.
- Execution owns runner lifecycle and executor invocation.
- Resource requests are declarative; executors decide what they can enforce.
- Future executor/plugin support should populate the same descriptor and
  capability contracts rather than replacing them.
- Persisted runtime metadata should be inspectable, safe, schema-versioned, and
  separate from lifecycle status.
- Operational choices are provenance facts by default, not semantic inputs.

## Key Design Choices

- Split `loom.pipeline.runtime` into an import-light package/facade with focused
  submodules such as options, profiles, environment, validation, registry, and
  serialization when needed.
- Keep `ResourceRequest` and `ResourceEntry` in `loom.pipeline.resources`.
- Keep existing `RuntimeRequest` as a compatibility/foundation model exposed by
  the runtime facade.
- Use `RunOptions` as the public invocation aggregate with fields for run URI,
  executor, dry-run, profile, tags, notes, planning-owned selector/resume
  adapters, execution settings, exact stage options, and adapter options.
- Keep execution `RunRequest` as the public runner envelope, but make
  `RunRequest.options: RunOptions` the only canonical source for
  invocation-policy semantics. Existing overlapping `RunRequest` constructor
  fields may be retained as transitional compatibility inputs only when they
  normalize into `RunOptions` without conflict; runner, planner adapter, CLI,
  config, and store code should read the normalized `RunOptions` rather than
  parallel `RunRequest` fields after v4 wiring is complete.
- Carry resolved per-stage runtime data into executor-facing stage requests as a
  first-class request field, not through untyped metadata.
- Use deterministic precedence: config base < selected runtime profile <
  explicit CLI/API invocation options.
- Merge mappings shallowly unless a typed model owns stricter behavior; replace
  scalar values and lists/tuples; merge stage options by exact stage ID.
- Add `StageRuntimeOptions(resources, execution, environment, adapter_options)`
  as runtime/profile data, not `StageSpec` semantics.
- Distinguish the full in-memory resolved stage runtime handoff from persisted
  runtime metadata: future executors may receive normalized environment request
  data in memory, but `runtime.json` records only safe summaries by default.
- Add environment request models but do not apply environment to local
  in-process execution or persist environment keys/values in v4.
- Hard-swap resources to `ResourceRequest(entries={...})` with `ResourceEntry`
  and built-in `cpu`, `memory`, and `gpu` validators.
- Define `ResourceEntry` around `kind`, `amount`, optional `unit`, and
  `attributes`, with resource-kind syntax and validators owned by
  `loom.pipeline.resources`.
- Use an explicit, deterministic resource validator registry rather than
  process-global mutable registration. The built-in default registry should be
  immutable or copy-on-write; callers that need additional kinds provide a
  composed registry during parsing/validation. Duplicate resource-kind
  registration fails with a path-aware error in v4.
- Require `ResourceRequest.entries` keys to match each `ResourceEntry.kind`,
  giving merge, serialization, and capability diagnostics one stable resource
  identity.
- Keep resource entry validation separate from executor capability validation:
  resources validate shape and known kinds, while executor descriptors report
  whether a selected executor can honor those validated kinds.
- Reject unregistered resource kinds with path-aware errors in v4. The
  validator surface should be registration-capable so later adapter or plugin
  phases can register owned kinds before validating authored runtime data.
- Reject old `cpus`, `memory_mb`, and `gpus` authored keys and constructor
  aliases.
- Add structured executor descriptor/capability records with diagnostic policy
  instead of string-only support statuses.
- Preserve adapter namespaces as plain data and warn for unclaimed namespaces.
- Add runtime/capability preflight checks with stable IDs:
  `runtime.options`, `runtime.profile`, `runtime.stage_options`,
  `executor.resolve`, `executor.capabilities`, and `resources.capabilities`.
- Add explicit preflight group contracts for these IDs: runtime checks belong
  to `PreflightGroup.RUNTIME`, executor checks to `PreflightGroup.EXECUTOR`,
  and resource capability checks to `PreflightGroup.RESOURCES`.
- Add CLI flags for `--profile`, `--tag KEY=VALUE`, and `--note TEXT`, while
  keeping complex nested runtime/profile/adapter settings in config or Python
  API.
- Persist safe normalized runtime metadata in a separate `runtime.json` run
  record, not in lifecycle status.

## Conflicts And Tradeoffs

- API quality vs CLI immediacy: v4 keeps the public runtime API as the source of
  truth, then adapts CLI/config to it.
- Clean resource model vs compatibility: v4 intentionally breaks old resource
  fields to avoid carrying two public schemas into later executor phases.
- Exact stage IDs vs concise bulk configuration: v4 chooses explicit
  stage-option targeting and defers matching policy.
- Runtime profiles vs adapter lock-in: v4 preserves adapter namespaces but does
  not interpret SLURM/Docker/Apptainer schemas before their roadmap phases.
- Environment usefulness vs secret safety: v4 normalizes environment requests
  but does not apply or persist them.
- Warning noise vs silent ignored resources: local ignored resource requests
  warn by default so users know local execution is advisory.
- Separate `runtime.json` vs fewer files: a dedicated record keeps status
  focused and gives runtime metadata its own schema/version boundary.
- `RunOptions` vs existing `RunRequest`: v4 keeps `RunRequest` as the
  execution envelope to avoid widening runtime models into config/provenance
  concerns, but makes `RunOptions` the single invocation-policy source inside
  that envelope.

## Maintainability Assessment

The plan keeps maintainability centered on ownership and small review slices.
The runtime package owns invocation models and pure validation; resources own
typed resource entries; planning owns selectors/resume semantics; execution owns
runner lifecycle; stores own persisted runtime metadata; diagnostics owns
preflight result formatting; CLI owns presentation and argument parsing.

The `RunOptions` / `RunRequest` boundary keeps invocation policy from being
duplicated across runtime and execution layers. New code should normalize
config, CLI, and Python API inputs into `RunOptions` once, attach that object to
the execution `RunRequest`, and pass resolved stage runtime data explicitly to
stage execution requests.

The largest maintainability risk is the hard resource schema swap. The plan
isolates that change in Phase 2 so model, parser, serializer, docs, and tests
can be reviewed without also adding profiles, descriptors, or CLI wiring.

The second major risk is letting runtime become a catch-all package. The split
submodule design and `docs/structure.md` update in Phase 1 are intended to keep
profiles, options, environment, validation, and descriptors separately owned.

## Extensibility Assessment

V4 establishes extension points for later roadmap versions without implementing
those versions early:

- New resource behavior expands through registered resource entry kinds and
  validators. Executor descriptors and capability checks then decide whether a
  selected executor can honor each validated kind.
- New executors describe behavior through descriptors and structured
  capabilities.
- Future plugins can populate the same descriptor registry.
- Future adapter schemas can claim and validate preserved namespaces.
- Future subprocess/container phases can apply environment requests in isolated
  processes.
- Future stage-worker, subprocess, scheduler, and container phases can consume
  resolved per-stage runtime handoff data instead of reimplementing
  config/profile merge logic.
- Future executor request models can evolve from `StageExecutionRequest` with a
  typed resolved runtime field rather than recovering runtime policy from
  metadata or raw config.
- Future catalog/bundle/sweep work can read `runtime.json` as the runtime
  metadata source.

The design deliberately avoids first-class retry, timeout, scheduler, container,
remote-store, and plugin behavior until those roadmap phases own the semantics.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No glob/tag/group stage option matching | Exact IDs keep v4 deterministic and reviewable. | Revisit during sweeps/plugins or when repeated-stage groups become a concrete user need. |
| No local in-process environment application | Avoid process-global side effects and secret handling before isolated executors exist. | Revisit in subprocess/container phases. |
| No environment key/value recording | Avoid accidental secret disclosure. | Revisit with explicit audit/provenance policy and redaction tests. |
| No plugin discovery | V4 designs registry contracts but does not implement v11. | Revisit in v11 plugin discovery. |
| No third-party resource validator discovery | V4 establishes a registration-capable resource validation contract but no plugin loading. | Revisit in v11 plugin discovery or the first adapter phase that needs externally supplied resource kinds. |
| No SLURM/Docker/Apptainer schema interpretation | Keep v4 executor-neutral. | Revisit in v6, v14, and v15. |
| No retry/timeout/wall-time first-class fields | Semantics differ across subprocess, scheduler, and reliability contexts. | Revisit in v5, v6, and v16. |
| No worker consumption of resolved per-stage runtime handoff | V4 defines and records the handoff shape before isolated stage-worker process control exists. | Revisit in v5 subprocess/stage-worker execution. |
| Transitional overlapping `RunRequest` constructor inputs | Existing public runner callers may still use v3 fields while v4 makes `RunOptions` canonical. | Revisit after v4 adoption; remove or deprecate compatibility inputs once downstream callers use `RunRequest.options`. |
| Hard resource schema break with no runtime aliases | Keeps the canonical resource API clean for future expansion. | Revisit only for docs or migration tooling if downstream migration pain warrants it. |
| No raw adapter payload persistence | Avoid persisting unvalidated or secret-bearing adapter data before descriptors own summaries. | Revisit when adapter descriptors define safe persisted summaries. |

## Plan Quality Gate

- Status: passed on 2026-05-07
- Required reviewer: `loom_plan_reviewer`
- Required before: creating any v4 phase execution plan or starting Phase 1
  implementation
- Review focus:
  - maintainability of the split runtime package boundary;
  - reviewability of the hard resource schema swap;
  - future compatibility of typed resource entries, resource-kind validators,
    and unknown-kind behavior;
  - compatibility of descriptor/capability contracts with later plugin and
    executor roadmap phases;
  - sufficiency of the resolved per-stage runtime handoff for v5+ worker,
    scheduler, container, sweep, and catalog phases;
  - correctness of planning/execution/CLI/config ownership boundaries;
  - sufficiency of per-phase package, unit, contract, integration, e2e, and
    opt-in test expectations;
  - clarity of accepted technical debt and revisit triggers.
- Loop budget:
  - Initial review: used on 2026-05-07.
  - Gate refinement pass: used on 2026-05-07 to define the `RunOptions` /
    `RunRequest` boundary, deterministic resource validator registry behavior,
    runtime/resource preflight group contracts, and broader resource docs
    migration obligations.
  - Confirmation review: used on 2026-05-07.
- Initial review result:
  - Blocking finding: resolved in this refinement by making `RunOptions` the
    canonical invocation-policy model, keeping `RunRequest` as the execution
    envelope with `options: RunOptions`, and requiring resolved stage runtime on
    executor-facing requests.
  - Non-blocking findings: folded into Phase 2 and Phase 6 acceptance criteria
    and test obligations.
- Confirmation review result:
  - Ready for phase implementation: yes.
  - Blocking findings remaining: none.
  - Gate recommendation: pass.
- Current gate result: passed.

## Phased Implementation

### Phase 1 - Runtime Package Boundary

Status: merged
Branch: `codex/runtime-package-boundary`
PR: https://github.com/samcantrill/loom/pull/70

Goal:

- Establish the split runtime package/facade and source-structure boundary
  before adding new runtime models.

Scope:

- Convert `loom.pipeline.runtime` from a module into an import-light package
  with a stable public facade.
- Preserve existing `RuntimeRequest`, `RuntimeKind`, and `parse_runtime_request`
  public imports.
- Add only package scaffolding needed by later phases.
- Update package imports and `__all__` exports.
- Update `docs/structure.md` for the runtime package and executor descriptor
  boundary.

Out of scope:

- Resource schema refactor.
- `RunOptions`, profiles, environment models, executor descriptors, preflight
  integration, `runtime.json`, or CLI/config runtime mapping.

Acceptance criteria:

- Public runtime imports remain stable and cheap after the package split.
- Existing runtime/resource behavior and tests remain unchanged.
- `docs/structure.md` describes the new package boundary and import direction.
- Runtime package imports do not import CLI, diagnostics, executor
  implementations, plugins, or optional backends.

Test expectations:

- Package: import-light runtime facade and public exports.
- Unit: import-path compatibility and existing runtime request behavior.
- Contract: none beyond existing package/import contracts.
- Integration: existing suites remain green.
- E2E: existing local pipeline e2e remains green.
- Opt-in: none.

Design impact:

- Establishes runtime package ownership without behavior changes.

Future compatibility:

- Later phases can add `options`, `profiles`, `environment`, `registry`,
  `validation`, and optional `serialization` submodules without changing public
  imports.

Alternatives rejected:

- Keeping a single broad `runtime.py` module as v4 grows.
- Adding placeholder files with no immediate public or implementation use.

Debt introduced:

- Minimal scaffolding only; behavior lands in later phases.

Reviewability:

- Review as a low-risk package-boundary PR.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 1: Runtime Package Boundary`

Completion summary:

- Merged on 2026-05-07 via PR #70 into `develop`.
- Implementation converted `loom.pipeline.runtime` from a module into an
  import-light package facade backed by a private `_models.py` leaf, preserving
  `RuntimeKind`, `RuntimeRequest`, `parse_runtime_request`, and
  `RUNTIME_SCHEMA_VERSION` imports through both `loom.pipeline.runtime` and
  `loom.pipeline`.
- Added package/unit coverage for runtime facade import compatibility and
  forbidden import boundaries; existing runtime request behavior and
  serialization remain unchanged.
- Updated `docs/structure.md` to document the runtime package boundary and
  future executor descriptor import direction without implementing descriptor
  behavior.
- Validation evidence: `make validate-pr` passed before PR opening; GitHub CI
  `checks` passed on PR #70; `make test-summary` reported 963 passed, 10
  skipped, and 579 deselected.
- Follow-up for Phase 2: the runtime package boundary is available; keep the
  resource schema hard swap scoped to `loom.pipeline.resources` and existing
  runtime request resource integration.

### Phase 2 - Typed Resource Entries

Status: merged
Branch: `codex/typed-resource-entries`
PR: https://github.com/samcantrill/loom/pull/71

Goal:

- Hard-swap the resource schema to typed resource entries.

Scope:

- Implement `ResourceEntry(kind, amount, unit, attributes)` using
  plain-data-compatible attributes.
- Replace canonical `ResourceRequest(cpus, memory_mb, gpus, custom)` with
  `ResourceRequest(entries={...})`.
- Define resource entry kind syntax, validator ownership, registration surface,
  and unknown-kind failure behavior.
- Define resource-kind syntax as lowercase ASCII identifier segments separated
  by dots, with built-ins using unqualified kinds such as `cpu`, `memory`, and
  `gpu` and future plugin/adapter kinds able to use qualified names.
- Implement validator registration through an explicit registry object or
  copy-on-write default registry. Do not rely on hidden process-global mutable
  state.
- Specify duplicate registration, registry composition, and test isolation
  behavior. In v4, duplicate registrations for the same kind fail rather than
  replace existing validators.
- Add built-in resource entry validation for `cpu`, `memory`, and `gpu`.
- Reject old `cpus`, `memory_mb`, and `gpus` authored keys and constructor
  aliases.
- Update `StageSpec.resources`, `StageSpec.resource_request`,
  `RuntimeRequest.resources`, public exports, docs, and tests for the entry
  model.
- Explicitly update `docs/features/runtime-resources.md` so it no longer
  documents `cpus`, `memory_mb`, `gpus`, or `custom` as the canonical
  post-v4 resource schema.
- Update or clearly mark historical all canonical resource examples in related
  feature docs and user-facing examples, including `docs/features/pipeline.md`,
  so the post-v4 documentation does not present conflicting resource schemas.
- Preserve resource immutability and plain-data serialization.

Out of scope:

- `RunOptions`, profiles, executor descriptors, capability checks, preflight
  wiring, `runtime.json`, and CLI/config runtime mapping beyond required
  schema/test fixes.

Acceptance criteria:

- Public imports expose `ResourceEntry` and entry-based `ResourceRequest`.
- Authored resources accept canonical entry syntax.
- Entry mapping keys match each `ResourceEntry.kind`.
- Authored resources and constructors reject old resource fields.
- Built-in validators enforce `cpu`, `memory`, and `gpu` semantics, including
  valid amounts, units, and attributes.
- Unregistered resource kinds are rejected with path-aware errors unless a
  caller provides a composed validator registry through the resource validation
  API before parsing/validation.
- Validator registry behavior is deterministic: default built-ins do not mutate
  during tests, duplicate registration fails, and custom registries do not leak
  validators between parse/validation calls.
- Existing stage/resource tests are migrated to entry semantics.
- `docs/features/runtime-resources.md` matches the entry-based schema and no
  longer presents the old field schema as the future contract.
- Related feature docs and canonical examples no longer present old
  `cpus`/`memory_mb`/`gpus`/`custom` examples as current v4 behavior.
- No semantic fingerprint behavior changes.

Test expectations:

- Package: resource facades and public exports.
- Unit: `ResourceEntry`, built-in validators, unregistered-kind rejection,
  deterministic validator registry behavior, duplicate-registration rejection,
  registry isolation, serialization, old-key rejection, stage resource parsing,
  and `RuntimeRequest` resource serialization.
- Contract: resource request plain-data contract and immutability.
- Integration: existing local pipeline/config resource fixtures migrated.
- E2E: existing local pipeline e2e remains green after schema migration.
- Opt-in: none.

Design impact:

- Introduces the intentional breaking v4 resource schema change.

Future compatibility:

- Future resources extend by registering entry kinds and validators rather than
  adding fields on `ResourceRequest`.
- Future plugin/adapter resource validators can be introduced by composing
  explicit registries before validation rather than mutating global state.
- Executor capability validation remains separate, so adding a resource kind
  does not automatically imply every executor can honor it.

Alternatives rejected:

- Fixed top-level CPU/memory/GPU fields.
- Compatibility aliases for old `cpus`, `memory_mb`, or `gpus` keys.
- Untyped `custom` as the primary extension mechanism.

Debt introduced:

- Downstream configs must migrate to entry syntax; runtime aliases are not
  provided.
- Plugin or adapter-supplied resource validators are not discovered in v4; only
  explicit in-process registry composition is available.

Reviewability:

- Review as the hard schema refactor.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 2: Typed Resource Entries`

Completion summary:

- Merged on 2026-05-07 via PR #71 into `develop`.
- Implementation hard-swapped the resource model to schema-versioned
  `ResourceRequest(entries={...})` with immutable
  `ResourceEntry(kind, amount, unit, attributes)` leaves.
- Added deterministic explicit resource validator registry composition with
  built-in `cpu`, `memory`, and `gpu` validators, duplicate-kind rejection,
  custom registry isolation, unregistered-kind failures, resource-kind syntax
  validation, and key/kind matching.
- Rejected removed `cpus`, `memory_mb`, `gpus`, and `custom` constructor,
  authored, and serialized resource fields rather than retaining aliases.
- Updated `StageSpec.resources`, `StageSpec.resource_request`,
  `RuntimeRequest.resources`, public `ResourceEntry` export, tests, docs, and
  canonical examples to the entry-based schema while keeping resources excluded
  from semantic fingerprints.
- Validation evidence: `make validate-pr` passed before PR opening and after
  the implementation refinement pass; GitHub CI `checks` passed on PR #71;
  `make test-summary` reported 1005 passed, 10 skipped, and 621 deselected.
- Follow-up for Phase 3: runtime option models can now reference the
  entry-based `ResourceRequest` without carrying old resource aliases.

### Phase 3 - Run Options And Environment Models

Status: merged
Branch: `codex/run-options-environment`
PR: https://github.com/samcantrill/loom/pull/72

Goal:

- Add core runtime invocation models before profile merge and workflow wiring.

Scope:

- Implement `RunOptions`.
- Implement `ExecutionOptions`.
- Implement `StageRuntimeOptions`.
- Implement run-level and stage-level environment request models.
- Define the adapter boundary from `RunOptions` to planning-owned
  `PlanSelectors` and `ResumeOptions` without moving selector or resume
  semantics into runtime.
- Define the execution-envelope boundary: `RunOptions` owns invocation policy;
  execution `RunRequest` later carries it as `options` while retaining
  config/pipeline/provenance/store/lifecycle fields.
- Add model serialization, validation basics, safe runtime metadata controls,
  and environment privacy defaults.
- Keep planning-owned selector/resume semantics with runtime-to-planning
  adapters.
- Exclude environment key/value recording and local environment application.

Out of scope:

- Runtime profile selection/merge.
- Executor descriptors and capability checks.
- Preflight checks.
- Persisted `runtime.json`.
- CLI flags.
- Plugin discovery or adapter schemas.

Acceptance criteria:

- Python callers can construct and serialize v4 runtime option models.
- `RunOptions` is documented and tested as the canonical source for run URI,
  executor, dry-run, profile, tags, notes, selector/resume adapters, execution
  settings, stage runtime options, environment requests, and adapter options.
- The model layer exposes a clear adapter from `RunOptions` into existing
  planning request types without duplicating planning semantics.
- Stage runtime options can represent resources, execution settings,
  environment requests, and adapter options.
- Environment keys/values are not recorded.
- Local in-process execution does not apply environment requests.
- Planning selector/resume ownership remains unchanged.

Test expectations:

- Package: public runtime model imports.
- Unit: option construction, environment privacy, stage-option validation,
  schema errors, and serialization.
- Contract: runtime option plain-data serialization, planning adapter contract,
  and execution-envelope boundary contract.
- Integration: Python API model construction with synthetic pipeline stage IDs
  where validation needs known stages.
- E2E: none required beyond existing suites unless phase implementation exposes
  user-facing behavior.
- Opt-in: none.

Design impact:

- Establishes the public runtime invocation aggregate.

Future compatibility:

- Provides the API future executors receive instead of ad hoc flags.
- Gives Phase 7 a single invocation-policy source to attach to `RunRequest`
  and resolve into stage execution requests.

Alternatives rejected:

- CLI-shaped option semantics.
- Moving planning selectors/resume into runtime.
- Applying environment in local in-process execution.

Debt introduced:

- No local environment application and no environment recording.

Reviewability:

- Review as pure model behavior before profile merge and command/store wiring.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 3: Run Options and Environment Models`

Completion summary:

- Merged on 2026-05-07 via PR #72 into `develop`.
- Implementation added import-light public runtime invocation models:
  `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`,
  `RunEnvironmentRequest`, and `StageEnvironmentRequest`, exported from
  `loom.pipeline.runtime` and `loom.pipeline`.
- Added strict plain-data serialization, immutable normalized mappings, safe
  metadata summaries, planning-owned selector/resume adapters, exact-stage
  validation, supplied known-stage validation, and Phase 2 entry-based
  `ResourceRequest` integration for stage runtime resources.
- Preserved the intended ownership boundary: no runtime profile merge, executor
  descriptor/capability checks, CLI/config mapping, preflight checks, persisted
  `runtime.json`, plugin discovery, local environment application, or runner
  request wiring was introduced.
- Automated review found no blocking findings. A stale PR-body GitHub-checks
  evidence row was corrected before merge.
- Validation evidence: `make validate-pr` passed during implementation
  refinement; GitHub CI `checks` passed on PR #72; `make test-summary`
  reported 1028 passed, 10 skipped, and 644 deselected.
- Follow-up for Phase 4: runtime profile merge can now target the canonical
  `RunOptions` and `StageRuntimeOptions` model shape without redefining
  resources, environment requests, or selector/resume adapters.

### Phase 4 - Runtime Profiles And Merge Semantics

Status: merged
Branch: `codex/runtime-profiles-merge`
PR: https://github.com/samcantrill/loom/pull/73

Goal:

- Add runtime profiles and deterministic option/profile merge behavior.

Scope:

- Implement `RuntimeProfile`.
- Implement profile collections and profile selection.
- Validate core profile sections strictly.
- Preserve adapter namespaces as plain data.
- Implement precedence and merge behavior:
  config base < selected profile < explicit CLI/API invocation options.
- Merge mappings shallowly unless a typed model owns stricter behavior.
- Replace scalar values and lists/tuples.
- Merge `stage_options` by exact stage ID.
- Support post-pipeline unknown-stage validation for stage options.

Out of scope:

- Executor descriptors.
- Preflight checks.
- Persisted `runtime.json`.
- CLI flags.
- Plugin discovery and adapter schemas.

Acceptance criteria:

- Python callers can normalize runtime options from base/profile/explicit
  sources.
- Stage options merge and validate by exact stage ID.
- Runtime profile core sections are strict.
- Adapter namespaces are preserved as plain data.
- Profile selection failures and schema failures are clear.

Test expectations:

- Package: profile model imports.
- Unit: profile selection/merge, adapter namespace preservation, exact stage-id
  validation, schema errors, and list/scalar replacement behavior.
- Contract: profile plain-data serialization and merge contract.
- Integration: config-shaped runtime/profile dicts normalize to expected
  options using synthetic pipeline stage IDs.
- E2E: none required beyond existing suites.
- Opt-in: none.

Design impact:

- Establishes deterministic runtime merge policy.

Future compatibility:

- Future adapter descriptors can claim preserved namespaces.

Alternatives rejected:

- Deep arbitrary merge for all fields.
- List concatenation.
- CLI-specific precedence.
- Glob, tag, or group stage matching.

Debt introduced:

- No glob/tag/group stage option matching.

Reviewability:

- Review as profile/merge semantics before descriptor and CLI wiring.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 4: Runtime Profiles and Merge Semantics`

Completion summary:

- Merged on 2026-05-07 via PR #73 into `develop`.
- Implementation added `RuntimeProfile`, `RuntimeProfileCollection`,
  profile parsing/selection helpers, and `merge_run_options`, exported from
  `loom.pipeline.runtime` and `loom.pipeline`.
- The merge contract now normalizes base/profile/explicit sources into
  canonical `RunOptions` with deterministic precedence, sparse mapping
  field-presence behavior, typed `RunOptions` as fully supplied sources,
  scalar/list replacement, shallow mapping merge, exact-stage option merge,
  resource-entry merge by kind, environment field merge, and no deletion or
  sentinel syntax.
- Runtime profile core sections validate through the existing Phase 3 runtime
  models, while non-core top-level profile sections are preserved as
  `adapter_options` namespaces and duplicate in-profile namespaces fail
  clearly.
- Preserved the intended ownership boundary: no executor descriptors,
  preflight checks, persisted `runtime.json`, CLI/config command mapping,
  plugins/adapter schemas, runner wiring, local environment application, or
  glob/tag/group stage matching were introduced.
- Automated review found no blocking findings; the expanded-path refinement
  pass fixed one documentation example so profile execution settings match the
  `ExecutionOptions.settings` shape.
- Validation evidence: `make validate-pr` passed during implementation;
  GitHub CI `checks` passed on PR #73; `make test-summary` reported 1047
  passed, 10 skipped, and 663 deselected.
- Follow-up for Phase 5: executor descriptor and capability validation can
  consume the resolved `RunOptions` output and preserved adapter namespaces
  without redefining profile merge behavior.

### Phase 5 - Executor Descriptors And Capability Validation

Status: merged
Branch: `codex/executor-capabilities`
PR: https://github.com/samcantrill/loom/pull/74

Goal:

- Add structured executor capability metadata and validation contracts.

Scope:

- Implement executor descriptor, structured capability, diagnostic policy, and
  registry contracts.
- Add built-in `local` descriptor without eager optional imports.
- Validate registered resource entry kinds against descriptor capabilities.
- Distinguish resource schema validation failures from executor capability
  diagnostics: unregistered resource kinds remain schema errors from Phase 2,
  while registered-but-unsupported kinds are capability warnings or errors based
  on descriptor policy.
- Warn for ignored local resources.
- Warn for unclaimed adapter namespaces.
- Keep executor implementations under `loom.pipeline.executors`.
- Keep runtime registry metadata/protocols import-light.

Out of scope:

- Preflight check wiring.
- Plugin discovery.
- SLURM, Docker, Apptainer, retry, timeout, remote-store, or sweep schemas.
- Executor implementation changes beyond descriptor registration.
- Persisted runtime metadata.

Acceptance criteria:

- Runtime validation can inspect executor capabilities without constructing
  executors.
- Unknown selected executors fail.
- Ignored local resources warn.
- Unclaimed adapter namespaces warn by default.
- Capability support is structured enough to carry support level, enforcement
  expectation, default severity, and diagnostic details.
- Fake descriptors can claim or reject resource kinds without changing the
  `ResourceRequest` schema.

Test expectations:

- Package: descriptor/registry imports remain cheap.
- Unit: capability records, registry behavior, registered resource capability
  validation, local descriptor behavior, unsupported-kind diagnostics, and
  adapter namespace warnings.
- Contract: descriptor protocol and fake descriptor validation contract.
- Integration: runtime/capability validation over synthetic configs.
- E2E: none required beyond existing suites.
- Opt-in: none.

Design impact:

- Creates plugin-ready executor metadata without implementing plugins.

Future compatibility:

- Later executor and plugin phases can populate the same descriptor registry.
- Later adapter and plugin phases can add descriptors for new resource kinds
  without changing the resource entry data model.

Alternatives rejected:

- Name-only registry.
- String-only capability statuses.
- Eager executor imports.
- Plugin discovery in v4.

Debt introduced:

- Adapter namespaces are not deeply validated until descriptors exist.

Reviewability:

- Review as extension contract before preflight wiring.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 5: Executor Descriptors and Capability Validation`

Completion summary:

- Merged on 2026-05-07 via PR #74.
- Added import-light executor descriptor and capability validation contracts,
  including `ExecutorDescriptor`, `ResourceCapability`,
  `CapabilityValidationResult`, deterministic descriptor registry behavior,
  and public `loom.pipeline.runtime`/`loom.pipeline` exports.
- Added the metadata-only default `local` descriptor. Unknown and
  whitespace-only explicit executor names now produce deterministic
  `executor.unknown` error diagnostics, while local `cpu`, `memory`, and `gpu`
  requests warn as ignored/not enforced without failing capability validation.
- Added adapter namespace ownership warnings without inspecting adapter
  payloads, plus unsupported-resource fallback diagnostics for registered
  resource kinds omitted by a descriptor.
- Preserved the intended boundary: no preflight check IDs or groups, plugin
  discovery, CLI/config mapping, `runtime.json` persistence, runner wiring,
  concrete executor behavior changes, resource schema changes, or adapter
  payload schema validation were introduced.
- Automated review found no blocking findings. The stale PR-body GitHub-check
  row was corrected before merge.
- Validation evidence: `make validate-pr` passed; GitHub CI `checks` passed on
  PR #74; `make test-summary` reported 1068 passed, 10 skipped, and 684
  deselected.
- Follow-up for Phase 6: map capability diagnostics into runtime preflight
  groups/check IDs and the explicit-load config/CLI behavior without moving
  descriptor logic into preflight.

### Phase 6 - Runtime Preflight And CLI/Config Mapping

Status: merged
Branch: `codex/runtime-preflight-cli-config`
PR: https://github.com/samcantrill/loom/pull/75

Goal:

- Expose runtime options through config/CLI inputs and preflight diagnostics.

Scope:

- Add config mapping for `runtime` and `runtime_profiles`.
- Update CLI mapping for `--profile`, `--executor`, `--run-uri`, `--dry-run`,
  selector/resume flags, repeatable `--tag KEY=VALUE`, and `--note TEXT`.
- Add preflight checks:
  - `runtime.options`
  - `runtime.profile`
  - `runtime.stage_options`
  - `executor.resolve`
  - `executor.capabilities`
  - `resources.capabilities`
- Add `PreflightGroup.RUNTIME` and `PreflightGroup.RESOURCES`, update
  `DEFAULT_PREFLIGHT_GROUPS` and `STABLE_CHECK_IDS`, and preserve the existing
  JSON shape for all new runtime, executor, and resource checks.
- Ensure CLI/config produce the same normalized runtime option objects as the
  Python API.
- Preserve v3 `--strict` warning escalation behavior.

Out of scope:

- Threading `RunOptions` through full run workflow.
- Persisted `runtime.json`.
- Raw adapter payload persistence.
- Environment key/value persistence.
- Plugin discovery.
- Executor-specific command behavior.
- Exposing every nested runtime/profile/adapter field as CLI flags.

Acceptance criteria:

- CLI and config map into normalized `RunOptions`.
- Tags and notes work through CLI and config/API pathways.
- Preflight reports runtime/profile/stage/executor/resource diagnostics with
  stable check IDs.
- Runtime checks are grouped under `runtime`, executor checks under `executor`,
  and resource capability checks under `resources`; group normalization, default
  group selection, and serialized JSON remain stable and contract-tested.
- Unknown profiles and unknown selected executors fail.
- Ignored resources and unclaimed adapter namespaces warn.
- `--strict` escalates warnings consistently with v3 behavior.

Test expectations:

- Package: CLI/config runtime mapping imports remain cheap.
- Unit: CLI tag/note parsing, config mapping, runtime check result formatting,
  and warning/strict behavior.
- Contract: CLI/config to runtime option mapping contract, `PreflightGroup`
  values, `STABLE_CHECK_IDS`, serialized JSON shape, and strict-mode warning
  escalation with the new runtime/resource checks.
- Integration: config/CLI to `RunOptions`, preflight runtime/capability checks.
- E2E: local preflight shows warnings for ignored requested resources.
- Opt-in: none.

Design impact:

- Makes runtime options user-facing before persisted run behavior.

Future compatibility:

- Future executor-specific CLI/config behavior can build on the same mapping
  and descriptor checks.

Alternatives rejected:

- Exposing every nested runtime/profile field as CLI flags.
- Keeping CLI option dataclasses as independent semantics.

Debt introduced:

- Complex nested stage/profile/adapter settings remain config/Python API only.

Reviewability:

- Review as user-input mapping and preflight behavior.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 6: Runtime Preflight and CLI/Config Mapping`

Completion summary:

- Merged on 2026-05-07 via PR #75.
- Added `src/loom/pipeline/runtime/config.py` with top-level `runtime` and
  `runtime_profiles` extraction plus `merge_config_run_options`, keeping
  config composition opaque and runtime merge semantics owned by the public
  runtime models.
- Added sparse CLI runtime option sources for `plan`, `preflight`, and `run`,
  covering profile, executor, run URI, dry-run, selectors, resume, repeatable
  tags, and repeatable notes without letting absent flags override
  config/profile values.
- Added `runtime` and `resources` preflight groups and stable checks for
  normalized runtime options, profile selection, exact-stage runtime options,
  executor resolution, executor capability diagnostics, and resource
  capability diagnostics.
- Mapped Phase 5 capability diagnostics into preflight results while preserving
  the descriptor ownership boundary and existing `executor.local` probing.
  Unknown executors fail `executor.resolve`; unresolved capability/resource
  checks skip; ignored local resources and unclaimed adapter namespaces warn
  and remain strict-mode escalatable.
- Automated review found one blocker in run/artifact-only run URI handling:
  CLI runtime options could force config composition even when an explicit
  run URI was present. The blocker was fixed before merge, with regression
  coverage for explicit runtime run URI and non-URI runtime flags against a
  missing config.
- Preserved the intended boundary: no runner/request runtime wiring,
  `runtime.json` persistence, raw adapter payload persistence, environment
  key/value persistence, plugin discovery, concrete non-local executor
  behavior, or nested adapter CLI syntax was introduced.
- Validation evidence: `make validate-pr` passed; GitHub CI `checks` passed on
  PR #75; `make test-summary` reported 1081 passed, 11 skipped, and 691
  deselected.
- Follow-up for Phase 7: thread the normalized `RunOptions` produced by this
  phase into run workflow requests, resolved per-stage runtime handoff, and
  safe persisted runtime metadata without redefining CLI/config parsing.

### Phase 7 - Run Workflow And Runtime Metadata

Status: merged
Branch: `codex/runtime-metadata-workflow`
PR: https://github.com/samcantrill/loom/pull/76

Goal:

- Thread normalized runtime options through validate/plan/run workflows and
  persist safe runtime metadata.

Scope:

- Thread normalized `RunOptions` through validate, plan, run, and preflight
  where relevant.
- Add `RunRequest.options: RunOptions` and migrate runner wiring so
  `PipelineRunner.run` and `run_pipeline` consume normalized `RunOptions` for
  invocation-policy fields. Existing overlapping `RunRequest` constructor
  fields may remain only as conflict-checked compatibility inputs that
  normalize into `options`.
- Keep planning and execution semantic boundaries intact.
- Resolve effective runtime data for every pipeline stage after
  base/profile/explicit option merge and exact stage-id validation.
- Add an in-memory worker/executor-ready resolved stage runtime handoff shape
  (`ResolvedStageRuntimeOptions` or an equivalent plain-data record) produced
  from normalized `RunOptions` rather than raw config/profile inputs.
- Add `StageExecutionRequest.resolved_runtime` or an equivalent typed
  executor-facing field so stage execution receives resolved runtime policy
  without reading raw config/profile data or untyped metadata.
- Add run-store `runtime.json` write/read APIs.
- Record safe normalized runtime metadata during runs as a persisted summary,
  not as the sole execution handoff.
- Include schema version, executor, selected profile, dry-run, tags, notes,
  resource entries, resolved stage runtime summaries keyed by exact stage ID,
  and adapter namespace presence or descriptor-validated summaries.
- Exclude environment keys and values.
- Do not persist raw unvalidated adapter payloads by default.
- Ensure runtime metadata is excluded from semantic fingerprints.

Out of scope:

- Raw adapter payload persistence.
- Environment key/value persistence.
- Plugin discovery.
- Executor-specific command behavior.
- Runtime fields affecting semantic fingerprints.

Acceptance criteria:

- Runs write schema-versioned `runtime.json`.
- Store APIs can write and read runtime metadata without CLI path walking.
- A future worker/executor can receive a resolved per-stage runtime API object
  for each canonical stage ID without re-running profile merge logic or parsing
  raw CLI/config data.
- Persisted `runtime.json` exposes only the safe summary of that resolved data,
  excluding environment keys/values and raw unvalidated adapter payloads.
- Runtime option changes affect `runtime.json` but not semantic fingerprints.
- Validate, plan, and run consume normalized runtime options where relevant.
- `RunRequest.options` is the runner's canonical invocation-policy field after
  normalization. If compatibility fields are retained, conflicting
  `RunRequest` and `RunOptions` values fail clearly instead of silently
  choosing one source.
- `PipelineRunner.run`, `run_pipeline`, planning adapters, CLI/config mapping,
  and store metadata all consume the same normalized `RunOptions`.
- `StageExecutionRequest` or an equivalent executor-facing request carries the
  resolved runtime handoff as a typed field; executor code does not recover this
  data from metadata.
- Planning and execution boundaries remain intact.
- Commands remain thin wrappers over public APIs.

Test expectations:

- Package: run-store runtime metadata API imports.
- Unit: runtime metadata serialization, resolved per-stage runtime summary
  construction, `RunRequest`/`RunOptions` normalization and conflict handling,
  `StageExecutionRequest` resolved-runtime field validation, and run-store
  read/write.
- Contract: run-store `runtime.json` contract, resolved stage runtime handoff
  contract, `RunRequest.options` invocation-policy contract, CLI/config/Python
  semantic equivalence, and fingerprint non-impact contract.
- Integration: plan/run/preflight wiring where relevant, local run writes
  `runtime.json`, and runner/executor request construction uses normalized
  `RunOptions` rather than legacy fields or raw config/profile data.
- E2E: local synthetic run with profile/resources/tags/notes, ignored-resource
  warnings, and unchanged fingerprints.
- Opt-in: none.

Design impact:

- Completes v4 by making the runtime API observable through real workflows.

Future compatibility:

- Gives run catalog, bundles, sweeps, diagnostics, and future executors a clear
  runtime metadata source.
- Gives v5 subprocess/stage-worker execution and later scheduler/container
  adapters a stable per-stage runtime handoff that is decoupled from raw
  profile/config representation.

Alternatives rejected:

- Status-embedded runtime metadata.
- Ad hoc CLI flag flow.
- Persisting raw adapter payloads or environment values.

Debt introduced:

- No raw adapter payload persistence and no environment recording.

Reviewability:

- Review as user-facing workflow wiring and persisted metadata behavior after
  model and descriptor foundations land.

Notes:

- PR feature focus: `Runtime Options`
- Intended PR title: `Runtime Options - Phase 7: Run Workflow and Runtime Metadata`

Completion summary:

- PR opened on 2026-05-07 against `develop` and merged on 2026-05-07.
- Merge commit: `df1397745eae25e0df2d4070f3c5862661908699`.
- Branch/worktree:
  `codex/runtime-metadata-workflow` /
  `/home/samcantrill/work/loom-worktrees/runtime-metadata-workflow`.
- Implementation adds `RunRequest.options` as the canonical invocation-policy
  field, typed per-stage resolved runtime handoff through
  `StageExecutionRequest.resolved_runtime`, safe run-store `runtime.json`
  read/write APIs, runner metadata writes, and CLI validate/plan/run
  normalized runtime option wiring.
- Validation before PR: `make validate-pr` passed, including Ruff, Pyright,
  default suite, config-extra suite, and build. `make test-summary` passed
  with package 50 passed / 1 skipped, unit 559 passed / 1 skipped, contract 53
  passed / 2 skipped, integration 15 passed / 7 skipped / 7 deselected, e2e
  16 passed, and config-extra 397 passed / 693 deselected.
- Automated review: managing-agent review found and fixed allocated-run
  runtime metadata incorrectly recording a null run URI for Python API callers.
  GitHub CI `checks` passed after the fix.
