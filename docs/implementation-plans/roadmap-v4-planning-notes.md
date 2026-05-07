# Roadmap v4 Planning Notes: Runtime Options And Resources

## Metadata

- Roadmap version: v4
- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`
- Previous version status: v3 implementation finalized, confirmed by user during
  v4 roadmap framing.
- Planning notes status: ready for implementation-plan drafting
- Current discussion stage: complete
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: confirmed; checkpoint reloaded after
    user resume
  - Design decision review: confirmed
  - Phase shaping: confirmed
  - Handoff: confirmed
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v3.md`
- Related feature docs:
  - `docs/features/runtime-resources.md`
  - `docs/features/execution.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/pipeline.md`
  - `docs/features/testing.md`
- Blockers: none known for planning.

## Roadmap Extraction

Baseline roadmap outcome:

- Define the shared operational control surface used by subprocess, SLURM,
  containers, sweeps, and preflight without mixing invocation choices into
  semantic pipeline specs.
- Add typed `RunOptions`, `ResumeOptions`, `ExecutionOptions`,
  `ResourceRequest`, and runtime profile models.
- Normalize and validate executor names, dry-run flags, resume settings,
  selector fields, tags, notes, and scheduler-neutral resource requests.
- Map config and CLI inputs into runtime option objects.
- Add capability-aware validation for resource fields without hard-coding
  executor-specific assumptions into the core resource model.
- Add an executor registry surface for resolving known executor names without
  loading optional backends eagerly.
- Add preflight checks for runtime option consistency and unsupported executor
  capability declarations.
- Cover normalization, validation, serialization, CLI/config mapping, and
  resource edge cases with tests.

Prerequisites:

- v0 local runtime kernel: pipeline specs, local planning, local execution,
  local run and artifact stores, resources foundation, runtime request
  foundation, fingerprints, provenance, and same-run-directory resume.
- v1 config composition: recursive includes, overlays, strict overrides,
  provenance, source records, and artifact-safe config inputs.
- v2 CLI core: `validate`, `plan`, and `run` commands with config overlays,
  selector flags, resume flags, dry-run summaries, `--format text|json`, and
  local `run_uri` behavior.
- v3 local diagnostics and preflight: reusable diagnostics package, preflight
  result model, preflight CLI and `loom run` reuse, status/log inspection, and
  artifact diagnostics.
- Current foundation modules:
  - `src/loom/pipeline/resources.py` has schema-versioned `ResourceRequest`
    with `cpus`, `memory_mb`, `gpus`, and `custom`.
  - `src/loom/pipeline/runtime.py` has local-only `RuntimeRequest` with
    `kind`, `resources`, and `metadata`.
  - Deferred runtime/resource fields are currently rejected explicitly.

Primary feature docs:

- `runtime-resources.md`
- `execution.md`
- `preflight.md`
- `cli.md`
- `pipeline.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Stage-worker execution and subprocess process control.
- SLURM script generation or live scheduler operations.
- Docker, Apptainer, and container command mapping.
- Retry policy, timeout enforcement, and failure categorization.
- Parallel local scheduling.
- Remote stores, sweeps, run catalogs, run bundles, plugins, cleanup,
  retention, dashboards, and domain-specific runtime behavior.

Compatibility obligations:

- Keep pipeline specs semantic and portable across executors.
- Keep invocation-only options out of semantic fingerprints by default unless a
  later explicit fingerprint policy says otherwise.
- Preserve scheduler-neutral resource field names in core models.
- Keep executor-specific fields in profiles or adapter-owned namespaces rather
  than core stage/resource records.
- Keep public imports cheap and avoid eager loading of optional executor
  backends.
- Preserve CLI as the outer presentation layer; lower-level runtime,
  execution, pipeline, store, config, and diagnostics modules must not import
  `loom.cli`.
- Keep defaults testable without SLURM, Docker, Apptainer, cloud services,
  network access, or downstream project packages.
- Avoid new heavyweight runtime dependencies.

## User Intent

Target audience:

- Loom maintainers and downstream users preparing local pipelines for future
  non-local execution.

User-visible outcome:

- A well-designed public runtime/options API that keeps invocation choices
  separate from semantic pipeline specs and gives CLI/config code one canonical
  normalized control surface to construct and pass through.

Success criteria:

- Programmatic API calls, config runtime/profile settings, and CLI flags can all
  map into the same normalized option objects.
- The public Python runtime/options API is the source of truth; CLI and config
  layers construct or merge objects instead of defining separate semantics.
- Local `validate`, `plan`, `run`, and `preflight` consume normalized
  runtime/options objects end to end where runtime options are relevant.
- Runs record normalized runtime request/options as non-semantic provenance or
  run metadata where appropriate.
- Minimal generic runtime profile selection and merge behavior exists for core
  sections, with executor/adapter-owned namespaces preserved for future
  adapters.

Non-goals:

- Do not interpret SLURM, Docker, Apptainer, remote-store, retry, timeout, or
  sweep-specific options in v4.
- Do not add stage-worker execution, subprocess process control, scheduler
  script generation, container command construction, retry enforcement, timeout
  enforcement, or parallel local scheduling.
- Do not let CLI argument convenience define the public runtime/options model.
- Do not include invocation-only runtime fields in semantic pipeline
  fingerprints by default.

Constraints:

- Preserve `loom` as a domain-neutral runtime.
- Preserve `docs/structure.md` import boundaries.
- Treat authored configs as trusted project code.
- Prefer standard-library runtime model implementation and existing local helper
  APIs unless the detailed plan identifies a design reason for more.
- Optimize first for public Python API stability and design quality; CLI should
  leverage the API rather than drive the API shape.
- Design the runtime surface carefully to avoid locking core models into local,
  subprocess, SLURM, container, or sweep assumptions that would force broad
  refactoring later.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | V4 optimizes for a well-designed and well-considered public runtime/options API first; CLI/config mapping remains in scope but should leverage that API. Target audience is Loom maintainers and downstream users preparing pipelines for later non-local execution. V3 implementation is finalized. | Public Python API stability and design quality drive the plan before CLI ergonomics. | None. | Discover workflows, success criteria, non-goals, constraints, and operational realities. |
| Intent discovery | Programmatic API, config runtime profiles, and CLI flags should map into the same normalized option objects. Local `validate`, `plan`, `run`, and `preflight` should consume normalized runtime/options objects where relevant. Runs should record normalized runtime request/options as non-semantic provenance or run metadata where appropriate. V4 should include minimal generic profile selection and merge behavior while avoiding runtime design lock-in. | Public Python API is the source of truth; CLI/config consume it. Core profile sections are validated strictly; adapter-owned namespaces are preserved without SLURM/Docker interpretation. | None. | Sort roadmap capabilities into include, defer, maybe, and out of scope. |
| Feature brainstorming | Include first-class per-stage runtime options resolved by exact stage ID after pipeline construction. Keep `ResourceRequest` small but position it as an extensible declarative envelope with executor capability validation instead of a premature scheduler model. Add a built-in registry/descriptor/capability contract now, with plugin discovery deferred but structurally anticipated. | Stage runtime overrides live in runtime/profile data rather than semantic `StageSpec` behavior. Resource fields remain conservative in v4. Registry supports built-in descriptors and future plugin-populated descriptors without eager optional backend imports. | None. | Confirm concrete included behavior, defaults, failure behavior, observability, and deferrals. |
| Functionality and behavior confirmation | Config provides base runtime settings, selected profile overlays that base, and explicit CLI/API invocation options override both. Programmatic API calls may pass already-constructed options rather than mimic CLI parsing. V4 supports exact stage-id runtime overrides only; unknown stage IDs fail during validation after pipeline construction. Runtime environment requests are normalized but not applied to local in-process execution in v4. Environment provenance is excluded by default; selected keys may be recorded only through explicit opt-in. | Exact stage IDs only for per-stage overrides. No environment keys or values are stored by default. Runtime data remains non-semantic and excluded from fingerprints by default. | None. | Write checkpoint and reset/compact context before design decision review. |
| Context compaction/reset checkpoint | Functionality and behavior baseline recorded in this notes file. The next pass reloaded this file, the roadmap planning prompt, relevant feature docs, and current runtime/resource source before drafting the design-decision review queue. | Treat confirmed functionality and behavior as stable unless the user explicitly reopens it. | None. | Start design decision review from the checkpointed notes. |
| Design decision review | All queued v4 design decisions are confirmed: split runtime package, planning-owned selectors/resume semantics, `RunOptions`, deterministic merge behavior, profiles, per-stage options, environment privacy, hard resource entry schema swap, structured executor capabilities, adapter warnings, preflight checks, planning/execution integration, CLI/config mapping, separate `runtime.json`, fingerprint exclusion, schema policy, import/docs boundaries, testing strategy, and accepted debt. | Use confirmed design decisions as the source for phase shaping. | None. | Shape the confirmed design into reviewable implementation phases. |
| Phase shaping | User confirmed a finer seven-phase split: runtime package boundary, typed resource entries, run options/environment models, runtime profiles/merge semantics, executor descriptors/capability validation, runtime preflight and CLI/config mapping, and run workflow/runtime metadata. | Keep each phase focused on one dominant risk and review boundary. | None. | Record handoff inputs and confirm whether to draft the implementation plan. |
| Handoff | Planning notes are ready for implementation-plan drafting. Handoff inputs summarize confirmed functionality, design decisions, seven-phase sketch, risks, assumptions, and accepted debt. | Draft the implementation plan only after explicit user confirmation to enter the implementation-plan draft prompt. | None. | Enter `implementation-plan-draft.md` if requested. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| `RunOptions` model | include | Roadmap names it as the invocation-level aggregate for one run, and the user confirmed the public Python API should be the source of truth. | Exact ownership and field set need design review. |
| `ResumeOptions` model | include | Existing selectors and resume flags need a normalized typed home before subprocess and SLURM layers reuse them. | Must not change pipeline graph semantics. |
| `ExecutionOptions` model | include | Shared execution behavior such as fail-fast, log capture, environment, profile, and future parallelism need a typed boundary. | Parallel local scheduling remains deferred unless explicitly selected later. |
| Runtime profile models | include | Profiles let the same pipeline run locally or under later executor profiles without changing semantic pipeline specs. | Need strict core validation, preserved adapter-owned namespaces, and careful design to avoid lock-in. |
| Resource capability validation | include | Later executors need clear reporting when requested resources cannot be honored. | Core should stay scheduler-neutral. |
| Executor registry surface | include | CLI, preflight, and execution need to resolve known executor names without eager optional backend imports. | Plugin discovery remains later roadmap work. |
| CLI/config mapping into options | include | User confirmed programmatic API calls, config runtime profiles, and CLI flags should map into the same normalized objects. | Exact precedence between CLI, config, profile, and programmatic API needs design review. |
| Preflight runtime checks | include | V3 preflight can gain runtime option consistency checks once v4 models exist. | Should remain local/default-testable. |
| Runtime option run metadata/provenance | include | User confirmed runs should record normalized runtime request/options where appropriate. | Must be non-semantic by default and avoid fingerprint impact unless later policy changes it. |
| Per-stage runtime configuration and environment | include | User identified per-stage execution configuration and environments as a first-class requirement. | Should live in the runtime/profile layer rather than semantic `StageSpec` unless later design explicitly distinguishes semantic stage requirements from invocation policy. |
| Extensible resource request architecture | include | User wants to avoid early lock-in and preserve the ability to model arbitrary future resource behaviors. | Design review must consider whether a single generic dataclass is too rigid and whether typed resource kinds/capability-specific handlers are safer. |
| Adapter/plugin-ready executor structure | include | User wants v4 to support later adapter-specific and plugin-first executor support without significant refactor. | V4 should avoid implementing plugin discovery while designing registry/capability contracts that can be backed by plugins later. |

## Confirmed Functionality And Behavior

Included functionality:

- Typed public runtime/options API centered on `RunOptions`, `ResumeOptions`,
  `ExecutionOptions`, runtime profile models, per-stage runtime options, and an
  extensible `ResourceRequest` architecture.
- Runtime/profile/config/CLI normalization so programmatic API calls, authored
  config runtime settings, selected runtime profiles, and CLI flags can produce
  the same normalized option objects.
- Option precedence where config supplies base runtime settings, selected
  profile settings overlay that base, and explicit CLI/API invocation options
  override both.
- First-class per-stage runtime configuration and environment requests resolved
  by exact stage ID after pipeline construction.
- Typed-entry resource requests replace first-class CPU/memory/GPU fields while
  positioning resources as a declarative envelope validated by resource-kind
  validators and checked against executor capabilities.
- Executor registry, descriptor, and capability contracts for built-in
  executors, designed so future plugin discovery can populate the same
  contracts without replacing them.
- Runtime option consistency and executor capability checks in preflight.
- Normalized runtime request/options recording as non-semantic run metadata or
  provenance where appropriate, with environment provenance excluded by default.

User-visible behavior:

- Downstream users and maintainers can construct normalized runtime options
  through Python APIs and rely on CLI/config paths to use the same semantics.
- Local `validate`, `plan`, `run`, and `preflight` consume normalized runtime
  options where runtime settings are relevant.
- Per-stage runtime overrides are addressed by exact stage ID and fail clearly
  when the stage ID does not exist in the constructed pipeline.
- Preflight can report runtime option consistency problems and selected
  executor capability mismatches without instantiating optional backends eagerly.
- Runs can expose safe normalized runtime metadata for debugging and
  provenance without treating invocation-only settings as semantic inputs.

Default behavior:

- Public Python API design quality and future compatibility take priority over
  CLI argument convenience.
- Programmatic API calls may pass already-constructed option objects and do not
  need to mimic CLI parsing.
- Runtime profile core sections are validated strictly; adapter-owned
  namespaces are preserved as plain data unless a registered descriptor owns
  validation.
- Only exact stage-id overrides are supported in v4.
- No environment keys or values are stored by default. Recording selected
  environment keys is an explicit opt-in behavior.
- Environment requests are normalized as runtime data but are not applied to
  local in-process execution in v4.
- Runtime options and resources do not affect semantic fingerprints by default.

Failure behavior and diagnostics:

- Unknown executor names fail during runtime option validation or preflight
  with clear diagnostics.
- Unknown profile names fail during normalization.
- Invalid core runtime/profile sections fail strictly.
- Unknown per-stage override IDs fail after pipeline construction, when the
  valid stage set is known.
- Unsupported resource requests or executor capability mismatches are reported
  through validation or preflight according to whether execution would
  definitely fail or the executor would merely ignore a request.
- Environment provenance remains absent unless explicitly opted in, reducing
  accidental secret disclosure.

Explicit deferrals:

- Glob, tag, group, or pattern-based per-stage runtime override matching.
- Applying environment mappings to local in-process execution.
- Persisting environment keys or values by default.
- Adding `wall_time_seconds`, timeout, retry, scheduler, container, or
  remote-store fields as first-class core resource/runtime fields.
- SLURM, Docker, Apptainer, subprocess, retry, timeout, sweep, or remote-store
  option interpretation.
- Plugin discovery and entry point loading.
- Parallel local scheduling.

Out-of-scope behavior:

- Stage-worker execution and subprocess process control.
- Scheduler script generation or live submission.
- Container command construction.
- Retry and timeout enforcement.
- Domain-specific runtime behavior.
- Broad runtime policy language or arbitrary profile inheritance.

Context compaction/reset checkpoint:

- Checkpoint status: complete; reset or compact context before design decision
  review.
- Notes path: `docs/implementation-plans/roadmap-v4-planning-notes.md`
- Resume instruction: reread this planning notes file and
  `.codex/prompts/roadmap-version-planning-notes-facilitate.md`, then reload
  `docs/implementation-plans/implementation-roadmap.md`,
  `docs/features/runtime-resources.md`, `docs/features/execution.md`,
  `docs/features/preflight.md`, `docs/features/cli.md`,
  `docs/features/pipeline.md`, `docs/features/testing.md`,
  `src/loom/pipeline/runtime.py`, and `src/loom/pipeline/resources.py`.
  Continue by drafting the complete design-decision review queue implied by
  the confirmed functionality and behavior. Do not reopen functionality or
  behavior unless the user explicitly asks.
- Functionality and behavior reopened after checkpoint: no

## Design Decision Review Queue

| Decision | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- |
| Runtime API ownership and public surface | V4 introduces durable public models around `RunOptions`, `ExecutionOptions`, profiles, stage options, and the existing local-only `RuntimeRequest`. Ownership must preserve pipeline/config/CLI boundaries and avoid duplicating planning models. | User confirmed a split `loom.pipeline.runtime` package with stable facade, focused submodules, resources remaining in `loom.pipeline.resources`, and lightweight registry/descriptors under runtime while executor implementations stay under executors. | confirmed |
| Resume and selector option ownership | `ResumeOptions` already exists in `loom.pipeline.planning` with minimal scope, while v4 wants normalized resume and selector fields shared by CLI, planning, run, and preflight. | User agreed to avoid moving planning semantics into runtime. Record selected approach in design decisions after batch closeout. | confirmed |
| RunOptions field set and semantics | The aggregate object will become the main invocation contract for future executors. Field choices around run URI, executor, dry-run, tags, notes, profile, stage options, resources, and execution settings will be hard to revise later. | User accepted the recommended field set if it provides a good foundation for future expansion. Record selected approach in design decisions after batch closeout. | confirmed |
| Option source precedence and merge semantics | Config, selected profiles, CLI flags, and programmatic API inputs must compose predictably without CLI-only behavior. Merge rules also affect source attribution and error messages. | User agreed to config base < selected profile < explicit CLI/API precedence; shallow mapping merge, scalar/list replace, stage options by exact stage ID, and adapter options by namespace/plain-data merge. | confirmed |
| Runtime profile model and adapter namespace preservation | Profiles need strict validation for core sections while preserving future `slurm`, `docker`, plugin, or adapter-owned sections without interpreting them early. | User agreed to strict core sections plus preserved `adapter_options` namespaces, with future registered descriptors able to own validation. Additional impact explanation provided before continuing. | confirmed |
| Per-stage runtime options model | Per-stage execution configuration and environments are first-class requirements, but they must not turn `StageSpec` into executor policy or create an implicit pattern language. | User agreed to exact stage IDs, post-pipeline validation, stage-level overlay of run/profile settings, and `StageRuntimeOptions(resources, execution, environment, adapter_options)`. Additional impact explanation provided before continuing. | confirmed |
| Environment request and privacy model | Environment requests can be operationally important and may contain secrets. V4 must normalize them without applying local in-process mutation or recording secrets by default. | User chose to design for explicit opt-in environment-key recording but defer implementation. V4 records no environment keys or values. | confirmed |
| ResourceRequest extensibility architecture | Existing `ResourceRequest` is small and scheduler-neutral; future arbitrary resources may not fit a fixed dataclass. V4 needs a design that supports future typed dimensions without becoming a premature scheduler model. | User selected a hard schema swap to typed-entry `ResourceRequest(entries={...})` with `ResourceEntry(kind, amount, unit, attributes)`-style entries and built-in handling for CPU/memory/GPU resource kinds. No compatibility aliases for current `cpus`, `memory_mb`, or `gpus` keys should be supported in v4. | confirmed |
| Resource merge and capability validation semantics | Stage resources, profile defaults, per-stage overrides, and executor capabilities must combine without changing semantic fingerprints by default. | User chose explicit warning behavior by default when local execution ignores requested resources; detailed severity policy can be specified later. | confirmed |
| Executor registry, descriptor, and capability contract | CLI, preflight, planning, and execution need one way to resolve executor names and capabilities without eager optional imports. The contract should later support plugins without refactor. | User chose a structured capability support model instead of string-only statuses. Use descriptors that expose resource-kind and runtime-feature support plus default diagnostic/severity policy. | confirmed |
| Adapter-specific option validation boundary | V4 should preserve adapter namespaces but not implement SLURM/Docker semantics. Registered descriptors may still need to validate owned namespaces later. | User agreed to core strict validation plus preserved adapter namespaces, with warnings for unclaimed/unregistered adapter namespaces. | confirmed |
| Preflight runtime and capability checks | V3 preflight has stable check models and executor groups. V4 needs runtime-option consistency and capability diagnostics without duplicating execution validation. | User agreed to runtime/profile/stage/executor/resource check IDs and severity behavior: invalid runtime/profile/executor fails, ignored resources warn, unregistered adapter namespaces warn/skip by context, strict escalates warnings. | confirmed |
| Planning and execution integration boundary | `plan`, `run`, and execution should consume normalized runtime options, but planning owns stage selection/resume behavior and execution owns runner lifecycle. | User agreed to normalized `RunOptions` flowing into validate/plan/run/preflight while planning owns selectors/resume/invalidation and execution owns lifecycle/invocation. | confirmed |
| CLI and config mapping surface | CLI/config should leverage the runtime API, not define separate semantics. This affects command options, config keys, profile selection, override paths, and JSON output. | User agreed to config `runtime`/`runtime_profiles`, runtime-mapped CLI flags, complex nested settings in config/Python API, and adding CLI flags for tags and notes. | confirmed |
| Persisted runtime metadata and provenance schema | Runs should record safe normalized runtime metadata where appropriate, but environment is excluded by default and runtime options are non-semantic. | User agreed to a separate schema-versioned `runtime.json` run-store record to keep the data model clear. | confirmed |
| Fingerprint boundary and semantic policy | Runtime options and resources must not affect semantic fingerprints unless an explicit future policy says so. The boundary must be testable and documented. | User agreed: v4 adds no runtime-field fingerprint opt-in policy; changes affect runtime metadata/provenance but not semantic fingerprints. | confirmed |
| Serialization and compatibility policy | Public runtime/resource/profile models need plain-data serialization and versioning that can grow for future executors and plugins. | User agreed: schema-versioned plain data, unknown core fields rejected, adapter plain data preserved, hard resource schema swap with no compatibility aliases. | confirmed |
| Import boundaries, package layout, and docs routing | V4 may add or expand `loom.pipeline.runtime`, `resources`, executor registry modules, config adapters, diagnostics checks, and CLI adapters. `docs/structure.md` may need updating. | User agreed to update structure docs, keep runtime facade import-light, allow CLI/config/diagnostics to import runtime, prohibit runtime imports from CLI/diagnostics, and keep executor implementations under executors. | confirmed |
| Testing and review strategy | V4 changes public APIs and future extension contracts. It needs package, unit, contract, integration, e2e, and opt-in boundaries without real external systems. | User agreed to package, unit, contract, integration, e2e, and no opt-in coverage expectations. | confirmed |
| Accepted debt and revisit triggers | Some constraints are deliberate deferrals: no glob stage overrides, no local env application, no plugin discovery, no advanced resources, no timeout/retry enforcement. | User agreed to the listed accepted debt and revisit triggers. | confirmed |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Runtime API ownership and public surface | Split `loom.pipeline.runtime` into focused submodules with a stable import-light facade. Use `runtime.options` for `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, normalized invocation objects, and safe runtime metadata controls; `runtime.profiles` for profile models and merge behavior; `runtime.environment` for environment request and recording policy; `runtime.validation` for pure validation; optional `runtime.serialization` if serialization logic grows; and lightweight descriptor/capability contracts under `runtime.registry` while actual executor implementations stay under `loom.pipeline.executors`. Keep existing `RuntimeRequest` as a compatibility/foundation model under the runtime facade. Keep `ResourceRequest` in `loom.pipeline.resources`, with runtime models referencing or re-exporting it without duplicating it. | User preferred splitting into submodules now to support future roadmap versions and confirmed the proposed package design. | A single large `loom.pipeline.runtime.py` module; a new top-level `loom.runtime` package; moving `ResourceRequest` under runtime; putting all registry behavior under executor implementation modules only. | The package split keeps public imports stable while giving future subprocess, SLURM, container, plugin, and reliability phases room to add behavior without crowding one file or changing user imports. Keeping resources separate preserves their stage-facing meaning. Keeping executor implementations outside runtime avoids eager optional backend imports. | Improves maintainability by making ownership explicit before v4 adds multiple durable public models. The main cost is more files and facade discipline, so package import tests must enforce cheap public imports and clear `__all__` exports. | Gives later adapter and plugin work stable extension points: runtime/preflight can inspect descriptor data without importing executors, while executor implementations can evolve separately. Revisit if registry contracts grow execution behavior rather than metadata/capability descriptions. |
| Resume and selector option ownership | Keep planning as the owner of actual resume and selector semantics. `RunOptions` may carry normalized invocation fields, but planning receives or derives planning-owned `PlanSelectors` and `ResumeOptions`. Do not move planning decisions into runtime. | User agreed and explicitly preferred decoupled behavior. | Moving `ResumeOptions` and selector models fully into runtime; making runtime call planning internals; duplicating planning selector semantics in CLI/runtime. | Planning already owns selectors, resume decisions, invalidation, and explanations. Runtime should normalize invocation data, not decide what stages are eligible, stale, reusable, skipped, or blocked. | Reduces semantic drift by keeping one planning authority. The implementation must provide clear adapters from `RunOptions` to planning request models so CLI/preflight/run do not duplicate conversion logic. | Later executors can consume normalized options without inheriting planning logic. Revisit only if planning models become too narrow to represent accepted runtime invocation inputs without awkward adapters. |
| RunOptions field set and semantics | Use `RunOptions` as the public invocation aggregate with minimal v4 fields: `run_uri`, `executor`, `dry_run`, `profile`, `tags`, `notes`, selector invocation fields or planning-selector adapter input, `resume`, `execution`, `stage_options`, and `adapter_options`. Treat `executor`, `dry_run`, selectors/resume, execution, and stage options as invocation/execution-affecting; `run_uri` as location/identity; `tags` and `notes` as metadata/provenance-only; `profile` as a selection/merge input; and `adapter_options` as future adapter data. Make `RunOptions` the single canonical invocation-policy source. The existing execution `RunRequest` remains the runner envelope for config, pipeline, provenance, stores, and lifecycle inputs, but carries `options: RunOptions`; any retained overlapping `RunRequest` constructor inputs are transitional compatibility inputs that normalize into `RunOptions` and fail on conflict. Do not add retry, timeout, wall-time, scheduler, container, or remote-store fields in v4. | User accepted the recommended field set as a foundation for future expansion. Initial plan review required the `RunOptions` / `RunRequest` boundary to be explicit before phase work. | Adding scheduler/container/retry/timeout fields now; letting CLI option classes remain the aggregate invocation contract; using only ad hoc runner keyword arguments; creating a parallel `RunOptions` model beside `RunRequest` without a canonical owner. | The field set captures current CLI/config needs and future executor handoff without pre-implementing later roadmap semantics. Explicit semantics make fingerprint and metadata boundaries easier to test. Keeping `RunRequest` as an envelope avoids widening runtime models into config/provenance concerns while preventing duplicate invocation policy. | Centralizes invocation data and reduces ad hoc flag flow. The cost is needing careful conversion from existing CLI options, planning models, and existing runner request fields during migration. | Additive fields can be introduced as later roadmap versions own their semantics. Future executor-facing request models should receive typed resolved runtime fields from `RunOptions`, not recover policy from metadata or raw config. Revisit when v5/v6/v14/v16 need first-class timeout, command, scheduler, container, retry, or reliability models. |
| Option source precedence and merge semantics | Use deterministic precedence: config base < selected runtime profile < explicit CLI/API invocation options. Mapping fields merge shallowly unless their typed model defines stricter behavior. Scalar values replace. Lists and tuples replace rather than concatenate. `stage_options` merge by exact stage ID, then field-wise within each stage. `adapter_options` merge by namespace as plain data, with explicit override replacing conflicting scalar/list values. | User agreed. | Deep arbitrary merge for all fields; list concatenation; CLI-specific precedence rules; profile-only behavior without explicit API override layer. | Deterministic shallow merge is easier to explain and test, while still allowing profiles to supply defaults and invocation options to override them. List replacement avoids inherited flags accumulating unexpectedly. | Keeps normalization predictable and prevents CLI/config drift. The cost is that some advanced merge use cases may require users to restate a list or mapping rather than patching deep leaves. | Later versions can add field-specific merge policies when a concrete model owns the semantics. Revisit when adapter namespaces gain typed schemas or when profile inheritance/policy language is explicitly planned. |
| Runtime profile model and adapter namespace preservation | Define runtime profiles with strict core sections such as `executor`, `execution`, `stage_options`, and maybe metadata fields, plus `adapter_options` namespaces that preserve plain data for future adapters. Registered descriptors can later validate the namespaces they own. V4 records and passes adapter data but does not interpret SLURM, Docker, Apptainer, remote-store, retry, timeout, or sweep semantics. | User agreed and asked for more impact detail before continuing. | Rejecting all unknown adapter data; accepting arbitrary top-level unknown fields; defining SLURM/Docker schemas in v4; profile behavior only in CLI. | Profiles let downstream users select operational defaults such as local vs future cluster/container without rewriting the semantic pipeline. Strict core sections protect the public runtime API, while adapter namespaces avoid locking v4 into future executor details. | Keeps core profile validation maintainable and makes ownership clear. The cost is that adapter namespace data can be preserved but not deeply validated until an adapter descriptor exists. | Future executor/plugin work can attach validation and interpretation to the same namespace structure. Revisit when v6/v14/v15/v11 add registered adapter descriptors and typed namespace schemas. |
| Per-stage runtime options model | Add `StageRuntimeOptions` with stage-scoped `resources`, `execution`, `environment`, and `adapter_options`. Resolve only exact stage IDs in v4. Validate unknown stage IDs after pipeline construction, when valid stage IDs are known. Stage-level runtime options overlay run/profile settings but remain outside semantic `StageSpec` behavior. | User agreed and asked for more impact detail before continuing. | Putting per-stage runtime config directly in `StageSpec`; supporting glob/tag/group matching in v4; executor-specific stage fields; no first-class stage runtime overrides. | Many real pipelines need stage-specific resources or environment, but those choices should be invocation policy rather than semantic pipeline structure. Exact IDs keep behavior explicit and reviewable while preserving future room for pattern matching. | Centralizes stage runtime behavior and avoids a second hidden pipeline model. The cost is some verbosity for many stages and delayed validation until the pipeline exists. | Later versions can add tag/group/pattern selection, typed adapter schemas, or richer stage policy once exact-ID behavior is stable. Revisit in sweep, plugin, or executor phases when broad stage matching has concrete use cases. |
| Environment request and privacy model | Add environment request models for run-level and stage-level runtime data, but do not apply them to local in-process execution in v4. Do not record environment keys or values in run metadata by default. Design the model so a future explicit allow-list can record selected environment keys or redacted/presence metadata, but defer that opt-in recording implementation from v4. | User chose to design for opt-in key recording later but defer implementation now. | Applying environment to local in-process execution; recording all environment keys; recording raw values; implementing allow-list persistence in v4. | Environment is operationally useful for subprocess, scheduler, and container execution, but it commonly carries secrets. V4 should normalize intent without creating secret provenance or process-global local side effects. | Keeps v4 safe and simple while documenting the future privacy policy. The cost is that users cannot audit requested environment keys through persisted run metadata in v4. | Future executor phases can apply environment in isolated subprocess/container contexts. Revisit opt-in key recording when a concrete provenance/audit requirement exists and redaction behavior can be tested. |
| ResourceRequest extensibility architecture | Replace the public canonical resource model with a typed-entry envelope: `ResourceRequest(entries={...})`, where each entry is a `ResourceEntry` carrying a `kind`, optional amount/unit, and structured attributes. Provide built-in validation/normalization for CPU, memory, and GPU resource kinds, define resource-kind syntax as lowercase ASCII identifier segments separated by dots, reject unregistered resource kinds with path-aware schema errors, and avoid treating `cpus`, `memory_mb`, and `gpus` as durable top-level fields. Use an explicit immutable or copy-on-write validator registry; callers compose registries for custom kinds instead of mutating hidden process-global state, and duplicate registrations fail in v4. Make this a hard v4 schema swap: do not support old authored keys or constructor aliases for `cpus`, `memory_mb`, or `gpus`. Future resource behavior expands by composing resource entry validators, not by adding fields to `ResourceRequest`. | User preferred the typed-entry model, explicitly questioned first-class fields unless they truly exist across all resource request situations, and then selected a hard swap with no compatibility alias support. Initial plan review asked the validator registration surface to avoid global mutable coupling. | Continuing the fixed `ResourceRequest(cpus, memory_mb, gpus, custom)` dataclass as canonical; adding a `dimensions` sidecar while keeping first-class CPU/memory/GPU fields; relying only on untyped `custom` metadata; accepting old keys as compatibility aliases; process-global mutable validator registration. | Typed entries decouple resource representation from scheduler/container assumptions, let each resource kind own validation, and give future adapters/plugins a stable extension point. A hard swap keeps the v4 API clean and avoids carrying two resource shapes through future executor phases. Explicit registries avoid test pollution and plugin-order lock-in. | Improves long-term maintainability by preventing the resource model from becoming a growing field bag or a dual-schema parser. The cost is a breaking change across current source, tests, docs, and any downstream configs using `cpus`, `memory_mb`, or `gpus`; explicit registries add a small amount of API surface. | Future executors and plugins can add typed resources such as disk, scratch, node, license, accelerator, network, or GPU memory without changing the `ResourceRequest` envelope or mutating global state. Revisit only if downstream migration pain reveals a need for a standalone migration tool or doc, not runtime compatibility aliases. |
| Resource merge and capability validation semantics | Use resource precedence of stage spec resources < run/profile defaults < per-stage runtime resources < explicit invocation override. Missing fields mean no explicit request. Overrides replace field values; no arithmetic merging. Local executor ignoring requested resources should produce explicit warning behavior by default in preflight/capability diagnostics, while detailed severity policy can be specified later. Resources stay excluded from semantic fingerprints by default. | User chose warning behavior so ignored resource requests are explicit by default. | Quietly ignoring local resource requests; treating every ignored resource as execution failure; additive/arithmetic resource merges; including resources in fingerprints by default. | Warning makes current local behavior honest without blocking local runs only because an advisory resource request exists. Replacement semantics keep resource intent clear. | Makes preflight more transparent and avoids silent false confidence. The cost is potential warning noise for local runs until later executors can honor resources. | Future executor descriptors can promote selected unsupported resources from warning to error when execution would fail or semantics require enforcement. Revisit severity policy when subprocess, SLURM, and container descriptors are implemented. |
| Executor registry, descriptor, and capability contract | Add a lightweight executor registry and descriptor contract usable by runtime validation and preflight without constructing executors or importing optional backends eagerly. Descriptors include executor name, profile namespace, structured capability declarations, default diagnostic policy, and optional lazy factory reference. Capabilities should describe resource entry-kind support and runtime-feature support through structured records rather than bare strings; for example each resource kind can declare support level, whether it is enforced, default severity when ignored/unsupported, and diagnostic message details. Actual executor implementations remain under `loom.pipeline.executors`; runtime registry owns metadata/protocols only. | User preferred a more structured capability model over string/status-only support. | Name-only registry; string-only `supported|ignored|unsupported` capabilities without policy; eager executor construction during preflight; plugin discovery in v4. | Structured capabilities let preflight and future adapters report precise behavior without hard-coding executor logic into diagnostics. Keeping implementation factories lazy preserves import-light CLI/help behavior. | More structured capability records add design and test surface, but avoid scattered one-off capability decisions. Tests must keep the descriptor contract small enough to remain maintainable. | V11 plugin discovery can populate the same registry. V5/v6/v14/v15 can add descriptors that validate and interpret their own capabilities without changing `RunOptions` or preflight shape. Revisit if capability records start duplicating executor implementation logic. |
| Adapter-specific option validation boundary | Validate core runtime/profile sections strictly. Preserve `adapter_options.<namespace>` as plain data. If a registered descriptor owns a namespace, let it validate that namespace through a descriptor-owned hook or schema contract. If a namespace is unclaimed/unregistered, warn by default rather than silently accepting it; context can choose skip/info only when the namespace is clearly irrelevant to the selected executor. V4 does not interpret SLURM, Docker, Apptainer, retry, timeout, remote-store, or sweep namespaces. | User agreed to the boundary and specifically requested warnings. | Rejecting all unknown adapter namespaces; silently preserving all adapter namespaces; defining adapter-specific schemas in v4; treating unclaimed namespaces as fatal by default. | Warning preserves future-facing config without pretending Loom has validated it. Registered descriptors create a path to stronger validation when adapters arrive. | Keeps core validation strict while preventing adapter sprawl. The cost is possible warning noise for configs that include future namespaces before adapters exist. | Future adapter/plugin descriptors can claim namespaces and convert warnings into typed validation. Revisit when plugin discovery and adapter schema registration are implemented. |
| Preflight runtime and capability checks | Add v4 runtime/capability checks using stable IDs such as `runtime.options`, `runtime.profile`, `runtime.stage_options`, `executor.resolve`, `executor.capabilities`, and `resources.capabilities`. Runtime checks belong to a new `PreflightGroup.RUNTIME`, executor checks belong to `PreflightGroup.EXECUTOR`, and resource capability checks belong to a new `PreflightGroup.RESOURCES`; update `DEFAULT_PREFLIGHT_GROUPS`, `STABLE_CHECK_IDS`, JSON serialization contracts, and strict-mode tests. Invalid runtime options, unknown profiles, and unknown selected executors fail. Known executor ignored resources warn. Unregistered adapter namespaces warn by default, or skip/info only when context clearly makes them irrelevant. `--strict` escalates warnings to command failure consistently with v3 behavior. | User agreed. Initial plan review asked for explicit group and contract-test obligations because preflight groups and stable IDs are exact contract-tested values. | Folding runtime checks into generic config/pipeline checks; using unstructured exceptions; silently ignoring ignored resources or unclaimed namespaces; treating every capability mismatch as fatal; adding check IDs without updating `PreflightGroup` and `STABLE_CHECK_IDS` contracts. | Stable check IDs and severity rules keep diagnostics machine-readable and make executor behavior explicit before expensive execution. Explicit groups keep the CLI/API output predictable and avoid accidental contract drift. | Keeps preflight as the user-visible place for runtime compatibility diagnostics. The cost is coordinating runtime validation errors with diagnostics result formatting and updating exact contract tests. | Later executor phases can add descriptor-specific check IDs while preserving the v4 core check family. Revisit severity details as real subprocess, SLURM, and container descriptors land. |
| Planning and execution integration boundary | `validate`, `plan`, `run`, and `preflight` should normalize runtime options where relevant, but each owning layer keeps its semantics. `validate` can catch runtime/profile/stage-option shape errors without planning execution. `plan` receives normalized `RunOptions`, converts selector/resume inputs into planning-owned models, and may include runtime summary as non-semantic context. `run` receives the same normalized `RunOptions` through `RunRequest.options`; execution gets executor selection, dry-run, run URI, stage runtime options, and safe metadata from that object. Resolved per-stage runtime data is passed to `StageExecutionRequest` or an equivalent executor-facing typed field, not through raw metadata. Planning continues to own eligibility, resume, and invalidation. Execution continues to own runner lifecycle and executor invocation. | User agreed. Initial plan review required this relationship to existing `RunRequest` / `PipelineRunner.run(RunRequest)` API to be explicit. | Planning directly owning full runtime options; execution recomputing selector/resume behavior; CLI passing ad hoc flags separately to plan and run; treating dry-run as a pipeline spec field; attaching resolved runtime only as untyped metadata. | This keeps the public runtime API useful across commands without moving planning or execution responsibilities into it. `RunRequest` remains the execution envelope while `RunOptions` stays the single invocation-policy source. | Reduces flag drift across validate/plan/run/preflight. The cost is a migration pass to thread `RunOptions` through existing command and Python API call sites and conflict-check any transitional `RunRequest` inputs. | Future executors can consume resolved typed stage runtime data while planning remains executor-neutral. Revisit if future dry-run manifests need richer executor-owned planning context. |
| CLI and config mapping surface | Add config support for `runtime` and `runtime_profiles`. CLI flags map into `RunOptions` and override config/profile values, including `--profile`, `--executor`, `--run-uri`, `--dry-run`, selector/resume flags, repeatable `--tag KEY=VALUE`, and `--note TEXT`. CLI should not expose every nested stage/profile/adapter field in v4; complex per-stage runtime options and adapter namespaces live in config or Python API. Existing override mechanics can patch runtime config paths. | User requested CLI flags for tags and notes. | Keeping tags/notes Python/config-only; exposing every nested runtime field as flags; leaving CLI option dataclasses as independent semantics. | Tags and notes are simple invocation metadata and useful from terminals. Keeping complex nested settings in config/Python avoids an unwieldy CLI before the runtime API settles. | Keeps CLI thin and avoids duplicating merge semantics. The cost is adding parsing/validation for tag syntax and deciding text/JSON output placement. | Later phases can add executor-specific CLI groups once adapter schemas exist. Revisit nested CLI exposure only when repeated user workflows justify it. |
| Persisted runtime metadata and provenance schema | Add a separate run-store-owned, schema-versioned `runtime.json` record for safe normalized runtime metadata. Include core fields such as executor, selected profile, dry-run, tags, notes, resource entries, stage option summaries, and adapter namespace presence or descriptor-validated summaries. Exclude environment keys and values. Do not store raw unvalidated adapter payloads by default; descriptor-owned adapters may later define safe summaries. Keep runtime metadata separate from lifecycle status and semantic fingerprints. | User agreed and preferred a clear data model. | Embedding all runtime metadata in `status.json`; not persisting runtime metadata; storing raw adapter payloads by default; storing environment keys/values. | Runtime metadata is invocation provenance, not lifecycle state. A separate file keeps status focused, gives runtime metadata its own schema version, and makes later catalog/bundle/diagnostic readers simpler. | Adds one run-store record and API surface, but avoids status bloat and mixed concerns. Store APIs must make the record easy to read/write without CLI path walking. | Future executor descriptors can add safe adapter summaries to the same record. Revisit raw adapter payload persistence only with explicit redaction and adapter-owned schema policy. |
| Fingerprint boundary and semantic policy | Exclude runtime options, runtime profiles, executor selection, resources, environment, tags, notes, and adapter options from semantic fingerprints by default. V4 does not add an opt-in policy for runtime fields to affect fingerprints. If a user needs runtime values to affect a stage fingerprint, they must model those values explicitly through existing semantic stage fingerprint inputs or wait for a future explicit policy. Tests should prove runtime option changes alter runtime metadata/provenance but not stage semantic fingerprints. | User agreed. | Including resources or executor selection in fingerprints by default; adding a v4 runtime fingerprint opt-in policy; treating adapter options as semantic inputs. | Runtime options are operational invocation choices. Keeping them non-semantic preserves portable pipeline specs and avoids accidental cache invalidation from scheduler/container choices. | Keeps fingerprint behavior simple and defensible. The cost is that users with resource-sensitive nondeterminism must model it explicitly rather than relying on runtime options. | Revisit when a concrete fingerprint policy design exists for container images, resource-controlled nondeterminism, or environment-sensitive execution. |
| Serialization and compatibility policy | Use plain-data `to_dict`/`from_dict` serialization with schema versions for runtime, resource, profile, stage option, descriptor summary, and runtime metadata records. Reject unknown core fields. Preserve adapter namespaces as plain data unless descriptor-owned. Resource schema is a hard v4 swap to typed entries with no `cpus`, `memory_mb`, or `gpus` aliases. No runtime migration compatibility layer is added in v4; docs and tests must make the breaking resource change explicit. | User agreed. | Lenient unknown core fields; unversioned dicts; runtime compatibility aliases for old resource keys; eager migration layer. | Strict versioned plain data matches existing store/config patterns and makes compatibility expectations explicit. Hard resource swap avoids carrying two public schemas. | Improves reviewability and future migration discipline. The cost is a breaking change and more tests around schema errors. | Future schema changes should be additive where possible and explicitly versioned when not. Revisit if downstream usage justifies a separate migration tool. |
| Import boundaries, package layout, and docs routing | Update `docs/structure.md` for the split `loom.pipeline.runtime` package, resource entry model, and executor descriptor boundary. Keep `loom.pipeline.runtime` facade import-light. Allow `loom.cli`, `loom.config`, `loom.diagnostics`, planning, execution, and stores to import runtime models as needed. Runtime must not import CLI or diagnostics. Runtime registry may define descriptor protocols and metadata, but must not eagerly import executor implementations, plugins, or optional backends. Executor implementations stay under `loom.pipeline.executors`. | User agreed. | Leaving structure docs stale; putting executor implementations under runtime; allowing runtime to import CLI/diagnostics; hiding public models only in deep modules. | Clear package ownership is necessary because v4 creates public models used by many layers and future roadmap versions. | Maintains architectural boundaries and cheap imports. The cost is more public facade/export maintenance. | Future plugin discovery can attach to the descriptor boundary without changing imports. Revisit if descriptor metadata becomes executor implementation behavior. |
| Testing and review strategy | Require package tests for import-light public runtime/resource/registry imports; unit tests for runtime option normalization, profile merge, stage-option validation, environment privacy, typed resource entries, deterministic resource validator registries, structured capability records, serialization errors, schema rejection, and `RunRequest` / `RunOptions` conflict handling; contract tests for executor descriptor/capability protocol, resource validators, preflight groups/stable IDs/JSON shape, `RunRequest.options`, resolved stage runtime handoff, and run-store `runtime.json`; integration tests for config `runtime`/`runtime_profiles` to normalized `RunOptions`, CLI flags to options, preflight runtime/capability checks, runner request wiring, and run writes; e2e tests for a local synthetic pipeline using runtime profiles/resources/tags/notes with local ignored-resource warnings and unchanged semantic fingerprints. No opt-in tests requiring real SLURM, Docker, Apptainer, network, or plugin discovery. | User agreed. Initial plan review added obligations for validator isolation, preflight contract shape, and the `RunOptions` / `RunRequest` boundary. | Unit-only testing; relying on real external executors; skipping persisted metadata tests; omitting fingerprint non-impact tests; testing CLI/config/Python paths separately without proving semantic equivalence. | V4 changes durable APIs and extension contracts, so tests need to cover both model correctness and command/API integration. The canonical `RunOptions` contract needs direct tests so duplicate invocation semantics do not reappear later. | Broadens test surface but keeps it local and deterministic. The phase plan should assign tests by behavior cluster to keep PRs reviewable. | Later executor phases can add fake-command or opt-in external tests without changing v4 core expectations. |
| Accepted debt and revisit triggers | Accept these v4 deferrals: no glob/tag/group stage option matching, revisit during sweeps/plugins or concrete repeated-stage use cases; no local in-process environment application, revisit in subprocess/container phases; no environment key/value recording, revisit with explicit audit/provenance policy; no plugin discovery, revisit in v11; no SLURM/Docker/Apptainer schema interpretation, revisit in v6/v14/v15; no retry/timeout/wall-time first-class fields, revisit in v5/v6/v16 when semantics are concrete; no worker consumption of resolved per-stage runtime handoff until v5; transitional overlapping `RunRequest` inputs only as conflict-checked compatibility while `RunOptions` becomes canonical; hard resource schema break with no runtime aliases, revisit only for docs or migration tooling if downstream pain warrants it. | User agreed. | Implementing all matching/env/plugin/executor/reliability behavior in v4; adding runtime compatibility aliases for old resource fields; removing all existing `RunRequest` invocation inputs before downstream callers have a canonical migration path. | The accepted debt keeps v4 focused on the shared API/control surface instead of absorbing future executor and policy work. | Makes scope reviewable and prevents premature lock-in. The cost is some user-facing deferrals, transitional runner request cleanup, and a breaking resource schema. | Each debt item has a roadmap-linked trigger so later phases can expand deliberately. |

## Practical Design Notes

Public Python API surface:

- Runtime models should be split into submodules for future roadmap expansion
  while exposing a stable import facade.
- Candidate runtime package layout:
  - `loom.pipeline.runtime`: import-light public facade and compatibility home
    for existing `RuntimeRequest`.
  - `loom.pipeline.runtime.options`: `RunOptions`, `ExecutionOptions`,
    `StageRuntimeOptions`, environment request models, normalized invocation
    objects, and safe runtime metadata controls.
  - `loom.pipeline.runtime.profiles`: `RuntimeProfile`, profile collection,
    profile selection, profile merge provenance, core section validation, and
    adapter namespace preservation.
  - `loom.pipeline.runtime.registry`: executor descriptor, capability, and
    registry contracts if the design keeps registry under runtime; alternatively
    `loom.pipeline.executors.registry` can own executable descriptors while
    runtime imports only the lightweight protocol.
  - `loom.pipeline.runtime.validation`: runtime/profile/stage-option
    normalization and validation helpers that do not touch the filesystem.
  - `loom.pipeline.runtime.serialization`: plain-data helpers only if model
    serialization becomes too broad for the model modules.
- Existing `loom.pipeline.resources` should remain the canonical home for
  `ResourceRequest` unless the design review explicitly chooses a broader
  resource package. Runtime option models may reference and re-export resource
  models without duplicating them.
- Existing execution `RunRequest` should remain the runner envelope, but v4
  should attach normalized `RunOptions` as `RunRequest.options` and have runner,
  planner adapter, CLI/config, store metadata, and executor request
  construction read invocation policy from that object.
- If v4 keeps overlapping `RunRequest` constructor fields for compatibility,
  they should be normalized into `RunOptions` exactly once and conflicts should
  fail clearly.
- Resource model refactor requirements:
  - Replace `ResourceRequest(cpus, memory_mb, gpus, custom)` with
    `ResourceRequest(entries={...})` and add `ResourceEntry`.
  - Define built-in resource entry validators for `cpu`, `memory`, and `gpu`.
  - Use an explicit immutable or copy-on-write validator registry; custom
    validators are composed by passing a registry, not by mutating hidden global
    process state.
  - Duplicate resource-kind validator registration fails in v4, and registry
    composition must be test-isolated.
  - Reject old `cpus`, `memory_mb`, and `gpus` authored keys instead of
    normalizing them.
  - Update `StageSpec.resources` validation and `StageSpec.resource_request` to
    use the entry-based model.
  - Update `RuntimeRequest.resources`, runtime option models, serialization,
    and schema-versioned fixtures to emit/read `entries`.
  - Export `ResourceEntry` alongside `ResourceRequest` from public package
    facades.
  - Update unit, package, contract, integration, and e2e tests that currently
    construct or assert `cpus`, `memory_mb`, and `gpus`.
  - Update diagnostics and executor capability checks to reason about resource
    entry kinds instead of dataclass fields.
  - Update docs/examples, including `docs/features/runtime-resources.md` and
    `docs/features/pipeline.md`, and note the breaking v4 resource schema
    change in the implementation plan.

CLI surface:

- CLI maps into `RunOptions` rather than defining separate semantics.
- V4 CLI flags include `--profile`, `--executor`, `--run-uri`, `--dry-run`,
  selector/resume flags, repeatable `--tag KEY=VALUE`, and `--note TEXT` where
  relevant.
- CLI does not expose every nested stage/profile/adapter field in v4; complex
  per-stage runtime options and adapter namespaces live in config or Python API.
- Existing override mechanics can patch runtime config paths.

Persisted records and file layout:

- Add a separate run-store-owned `runtime.json` record with its own schema
  version.
- Keep runtime metadata out of lifecycle status and semantic fingerprints.
- Include safe normalized core runtime metadata, typed resource entries, stage
  option summaries, tags, notes, and adapter namespace presence or
  descriptor-validated summaries.
- Exclude environment keys and values.
- Do not persist raw unvalidated adapter payloads by default.

Import boundaries and dependencies:

- Add/split `loom.pipeline.runtime` as an import-light package with focused
  submodules and stable facade.
- Keep `ResourceRequest` and `ResourceEntry` in `loom.pipeline.resources`.
- Allow CLI, config, diagnostics, planning, execution, and stores to import
  runtime models.
- Runtime must not import CLI or diagnostics.
- Runtime registry owns lightweight descriptor/capability protocols and
  metadata only; executor implementations stay under
  `loom.pipeline.executors`.
- No eager optional backend imports and no new heavyweight runtime dependencies.

Failure modes and diagnostics:

- Invalid runtime options fail clearly.
- Unknown profiles fail.
- Unknown selected executors fail.
- Unknown stage IDs in stage options fail after pipeline construction.
- Known executors ignoring requested resources warn by default.
- Unclaimed adapter namespaces warn by default.
- V4 preflight adds stable checks such as `runtime.options`,
  `runtime.profile`, `runtime.stage_options`, `executor.resolve`,
  `executor.capabilities`, and `resources.capabilities`.
- `--strict` escalates warnings to command failure.

Extension points and flexibility boundaries:

- Typed resource entries extend by adding resource entry kinds and validators,
  not fields on `ResourceRequest`.
- Structured executor descriptors/capabilities can be populated by built-ins
  now and plugin discovery later.
- Adapter namespaces are preserved as plain data and later claimed by
  descriptors.
- Exact stage-id runtime options are the only v4 stage override mechanism.
- Plugin discovery, pattern matching, adapter schemas, environment application,
  and reliability policies are deferred.

Maintainability assessment:

- V4 centralizes runtime invocation data and removes ad hoc CLI/config flag
  semantics, improving consistency across validate, plan, run, and preflight.
- Splitting runtime into focused submodules prevents a single broad runtime file
  from absorbing profiles, options, registry, environment, and validation.
- The hard resource schema swap is the largest refactor risk and must be
  isolated into a coherent phase with comprehensive tests and docs.

Extensibility assessment:

- The confirmed design gives future executor, container, SLURM, sweep,
  reliability, and plugin phases stable contracts without implementing those
  systems early.
- Typed resources and structured capabilities are the main extensibility
  anchors.
- Adapter namespace preservation avoids premature rejection of future config
  while warnings prevent silent false validation.

Flexibility and expansion assessment:

- The design favors additive future growth through resource entry kinds,
  descriptor-owned adapter schemas, and additional runtime submodules.
- Exact stage-id overrides are deliberately conservative but can expand to
  tags/groups/patterns later if concrete use cases justify a matching policy.
- Runtime fingerprint exclusion keeps operational flexibility from invalidating
  semantic pipeline cache behavior.

Scalability and future compatibility:

- V4 is local/default-testable but prepares for subprocess, SLURM, containers,
  sweeps, run catalog/bundles, plugins, and reliability policies.
- The `runtime.json` record gives future diagnostics/catalog/bundle features a
  clear runtime metadata source.
- Schema-versioned plain data supports later explicit migrations.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No glob/tag/group stage option matching | Exact IDs keep v4 deterministic and reviewable. | Revisit during sweeps/plugins or when repeated-stage groups become a concrete user need. |
| No local in-process environment application | Avoid process-global side effects and secret handling before isolated executors exist. | Revisit in subprocess/container phases. |
| No environment key/value recording | Avoid accidental secret disclosure. | Revisit with explicit audit/provenance policy and redaction tests. |
| No plugin discovery | V4 designs registry contracts but does not implement v11. | Revisit in v11 plugin discovery. |
| No SLURM/Docker/Apptainer schema interpretation | Keep v4 executor-neutral. | Revisit in v6, v14, and v15. |
| No retry/timeout/wall-time first-class fields | Semantics differ across subprocess, scheduler, and reliability contexts. | Revisit in v5, v6, and v16. |
| Hard resource schema break with no runtime aliases | Keeps the canonical resource API clean for future expansion. | Revisit only for docs or migration tooling if downstream migration pain warrants it. |

## Phase Sketch

### Phase 1 - Runtime Package Boundary

Goal:

- Establish the split runtime package/facade and source-structure boundary
  before adding new runtime models.

Scope:

- Split `loom.pipeline.runtime` into an import-light package/facade and focused
  submodules as needed.
- Add placeholder-free public facade exports only for existing runtime symbols
  and any package scaffolding needed by later phases.
- Update `docs/structure.md` for the runtime package and executor descriptor
  boundary.
- Keep existing runtime/resource behavior unchanged except import path
  compatibility needed for the package split.

Out of scope:

- Resource schema refactor, `RunOptions`, profiles, executor descriptors,
  preflight integration, `runtime.json`, CLI/config mapping beyond required
  import/test fixes.

Acceptance criteria:

- Public runtime imports remain stable and cheap after converting
  `loom.pipeline.runtime` from a module into a package.
- Existing runtime/resource behavior and tests remain unchanged.
- Source-structure docs describe the new package boundary.

Test expectations:

- Package: import-light runtime facade and public exports.
- Unit: import-path compatibility and existing runtime request behavior.
- Contract: none beyond existing package/import contracts.
- Integration: existing suites remain green.
- E2E: existing local pipeline e2e remains green.
- Opt-in: none.

Design impact:

- Establishes runtime package ownership without changing behavior.

Future compatibility:

- Future phases can add `options`, `profiles`, `environment`, `registry`, and
  validation submodules without changing public imports.

Alternatives rejected:

- Keeping a single broad `runtime.py` module as v4 grows.

Debt introduced:

- Minimal scaffolding only; no behavior added in this phase.

Reviewability:

- Review as a low-risk package-boundary PR.

### Phase 2 - Typed Resource Entries

Goal:

- Hard-swap the resource schema to typed resource entries.

Scope:

- Implement `ResourceEntry` and hard-swap `ResourceRequest` to
  `entries={...}`.
- Define resource-kind syntax, validator ownership, registration behavior, and
  unregistered-kind schema errors.
- Implement validator registration through an explicit immutable or
  copy-on-write registry object; avoid hidden process-global mutable state.
- Define duplicate-registration failure and registry isolation behavior.
- Add built-in resource entry validation for `cpu`, `memory`, and `gpu`.
- Reject old `cpus`, `memory_mb`, and `gpus` authored keys and constructor
  aliases.
- Update `StageSpec.resources`, `StageSpec.resource_request`,
  `RuntimeRequest.resources`, public exports, docs, and tests for the entry
  model.
- Update all canonical resource examples in related feature docs and
  user-facing examples so old `cpus`, `memory_mb`, `gpus`, and `custom`
  examples are not presented as current v4 behavior.

Out of scope:

- `RunOptions`, profiles, executor descriptors, preflight integration,
  `runtime.json`, CLI/config mapping beyond required schema/test fixes.

Acceptance criteria:

- Public imports expose `ResourceEntry` and entry-based `ResourceRequest`.
- Authored resources accept canonical entry syntax and reject old resource
  fields.
- Entry mapping keys match each `ResourceEntry.kind`.
- Built-in validators enforce CPU, memory, and GPU entry semantics, and
  unregistered resource kinds fail unless a caller provides a composed
  validator registry explicitly.
- Validator registry behavior is deterministic, duplicate registration fails,
  and custom registry validation does not leak between tests or calls.
- Existing stage/resource tests are migrated to entry semantics.
- No semantic fingerprint behavior changes.

Test expectations:

- Package: resource facades and public exports.
- Unit: `ResourceEntry`, built-in validators, unregistered-kind rejection,
  deterministic validator registry behavior, duplicate-registration rejection,
  registry isolation, serialization, old-key rejection, stage resource parsing,
  `RuntimeRequest` resource serialization.
- Contract: resource request plain-data contract and immutability.
- Integration: existing local pipeline/config resource fixtures migrated.
- E2E: existing local pipeline e2e remains green after schema migration.
- Opt-in: none.

Design impact:

- Intentional breaking resource schema change.

Future compatibility:

- Future resources extend by composing entry-kind validators rather than adding
  fields or mutating global state.

Alternatives rejected:

- Fixed top-level CPU/memory/GPU fields and compatibility aliases.

Debt introduced:

- Downstream configs must migrate to entry syntax; runtime aliases are not
  provided.

Reviewability:

- Review as the hard schema refactor.

### Phase 3 - Run Options And Environment Models

Goal:

- Add core runtime invocation models before profile merge and workflow wiring.

Scope:

- Implement `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, and
  environment request models.
- Define `RunOptions` as the canonical invocation-policy model and document the
  later execution-envelope boundary where `RunRequest.options` carries it into
  the runner.
- Add model serialization, validation basics, safe runtime metadata controls,
  and environment privacy defaults.
- Keep planning-owned selector/resume semantics with runtime-to-planning
  adapters.
- Exclude environment key/value recording and local environment application.

Out of scope:

- Runtime profiles, profile selection/merge, executor descriptors/capability
  checks, preflight checks, persisted `runtime.json`, CLI flags, plugin
  discovery, adapter schemas.

Acceptance criteria:

- Python callers can construct and serialize v4 runtime option models.
- `RunOptions` is documented and tested as the single source for run URI,
  executor, dry-run, profile, tags, notes, selector/resume adapters, execution
  settings, stage options, environment requests, and adapter options.
- Stage runtime options can represent resources, execution settings,
  environment requests, and adapter options.
- Environment keys/values are not recorded and local in-process execution does
  not apply environment requests.
- Planning selector/resume ownership remains unchanged.

Test expectations:

- Package: public runtime model imports.
- Unit: option construction, environment privacy, stage-option validation,
  schema errors.
- Contract: runtime option plain-data serialization, planning adapter contract,
  and execution-envelope boundary contract.
- Integration: Python API model construction with synthetic pipeline stage IDs
  where validation needs known stages.
- E2E: none required beyond existing suites unless phase implementation
  exposes user-facing behavior.
- Opt-in: none.

Design impact:

- Establishes the public runtime invocation aggregate.

Future compatibility:

- Provides the API future executors receive instead of ad hoc flags and gives
  Phase 7 one policy object to attach to `RunRequest`.

Alternatives rejected:

- CLI-shaped option semantics, profile-only design, and moving planning
  selectors/resume into runtime.

Debt introduced:

- No local env application and no env recording.

Reviewability:

- Review as pure model behavior before profile merge and command/store wiring.

### Phase 4 - Runtime Profiles And Merge Semantics

Goal:

- Add runtime profiles and deterministic option/profile merge behavior.

Scope:

- Implement `RuntimeProfile`, profile collections, profile selection,
  strict core section validation, and adapter namespace preservation.
- Implement precedence and merge behavior: config base < selected profile <
  explicit CLI/API invocation options.
- Support exact stage-id stage options and post-pipeline unknown-stage
  validation.
- Preserve adapter namespaces as plain data and warn policy hooks for later
  descriptor phases where needed.

Out of scope:

- Executor descriptors, preflight checks, persisted `runtime.json`, CLI flags,
  plugin discovery, adapter schemas.

Acceptance criteria:

- Python callers can normalize runtime options from base/profile/explicit
  sources.
- Stage options merge and validate by exact stage ID.
- Runtime profile core sections are strict and adapter namespaces are preserved
  as plain data.

Test expectations:

- Package: profile model imports.
- Unit: profile selection/merge, adapter namespace preservation, exact stage-id
  validation, schema errors.
- Contract: profile plain-data serialization and merge contract.
- Integration: config-shaped runtime/profile dicts normalize to expected
  options using synthetic pipeline stage IDs.
- E2E: none required beyond existing suites.
- Opt-in: none.

Design impact:

- Establishes the deterministic runtime merge policy.

Future compatibility:

- Future adapter descriptors can claim preserved namespaces.

Alternatives rejected:

- Deep arbitrary merge for all fields, list concatenation, CLI-specific
  precedence, and glob/tag/group stage matching.

Debt introduced:

- No glob/tag/group stage matching.

Reviewability:

- Review as profile/merge semantics before descriptor and CLI wiring.

### Phase 5 - Executor Descriptors And Capability Validation

Goal:

- Add structured executor capability metadata and validation contracts.

Scope:

- Implement executor descriptor, structured capability, diagnostic policy, and
  registry contracts.
- Add built-in `local` descriptor without eager optional imports.
- Validate resource entry kinds against descriptor capabilities.
- Warn for ignored local resources and unclaimed adapter namespaces.

Out of scope:

- Preflight check wiring, plugin discovery, SLURM/Docker/Apptainer schemas,
  executor implementation changes beyond descriptor registration, persisted
  runtime metadata.

Acceptance criteria:

- Runtime validation can inspect executor capabilities without constructing
  executors.
- Unknown selected executors fail; ignored local resources warn; unclaimed
  adapter namespaces warn by default.

Test expectations:

- Package: descriptor/registry imports remain cheap.
- Unit: capability records, registry behavior, resource capability validation,
  adapter namespace warnings.
- Contract: descriptor protocol and fake descriptor validation contract.
- Integration: runtime/capability validation over synthetic configs.
- E2E: none required beyond existing suites.
- Opt-in: none.

Design impact:

- Creates plugin-ready executor metadata without implementing plugins.

Future compatibility:

- Later executor and plugin phases can populate the same descriptor registry.

Alternatives rejected:

- Name-only registry, string-only capability statuses, eager executor imports,
  and plugin discovery in v4.

Debt introduced:

- Adapter namespaces are not deeply validated until descriptors exist.

Reviewability:

- Review as extension contract before preflight wiring.

### Phase 6 - Runtime Preflight And CLI/Config Mapping

Goal:

- Expose runtime options through config/CLI inputs and preflight diagnostics.

Scope:

- Add config mapping for `runtime` and `runtime_profiles`.
- Update CLI mapping for `--profile`, `--executor`, `--run-uri`, `--dry-run`,
  selector/resume flags, repeatable `--tag KEY=VALUE`, and `--note TEXT`.
- Add preflight checks: `runtime.options`, `runtime.profile`,
  `runtime.stage_options`, `executor.resolve`, `executor.capabilities`, and
  `resources.capabilities`.
- Add `PreflightGroup.RUNTIME` and `PreflightGroup.RESOURCES`, update default
  group ordering and `STABLE_CHECK_IDS`, and preserve the existing serialized
  preflight JSON shape.
- Ensure CLI/config produce the same normalized runtime option objects as the
  Python API.

Out of scope:

- Threading `RunOptions` through full run workflow, persisted `runtime.json`,
  raw adapter payload persistence, environment key/value persistence, plugin
  discovery, executor-specific command behavior.

Acceptance criteria:

- CLI and config map into normalized `RunOptions`.
- Tags and notes work through CLI and config/API pathways.
- Preflight reports runtime/profile/stage/executor/resource diagnostics with
  stable check IDs.
- Runtime checks group under `runtime`, executor checks group under `executor`,
  and resource capability checks group under `resources`.
- `--strict` escalates warnings consistently with v3 behavior.

Test expectations:

- Package: CLI/config runtime mapping imports remain cheap.
- Unit: CLI tag/note parsing, config mapping, preflight check formatting.
- Contract: CLI/config to runtime option mapping contract, `PreflightGroup`
  values, `STABLE_CHECK_IDS`, serialized JSON shape, and strict-mode behavior
  with new runtime/resource warnings.
- Integration: config/CLI to `RunOptions`, preflight runtime/capability checks.
- E2E: local preflight shows warnings for ignored requested resources.
- Opt-in: none.

Design impact:

- Makes runtime options user-facing before persisted run behavior.

Future compatibility:

- Future executor-specific CLI/config behavior can build on the same mapping
  and descriptor checks.

Alternatives rejected:

- Exposing every nested runtime/profile field as CLI flags and keeping CLI
  option dataclasses as independent semantics.

Debt introduced:

- Complex nested stage/profile/adapter settings remain config/Python API only.

Reviewability:

- Review as user-input mapping and preflight behavior.

### Phase 7 - Run Workflow And Runtime Metadata

Goal:

- Thread normalized runtime options through validate/plan/run workflows and
  persist safe runtime metadata.

Scope:

- Thread normalized `RunOptions` through validate/plan/run/preflight where
  relevant.
- Add `RunRequest.options: RunOptions` and migrate runner wiring so
  `PipelineRunner.run` and `run_pipeline` consume normalized `RunOptions` for
  invocation-policy fields.
- Keep planning and execution semantic boundaries intact.
- Resolve effective runtime data for every pipeline stage after
  base/profile/explicit option merge and exact stage-id validation.
- Add an in-memory worker/executor-ready resolved stage runtime handoff shape
  produced from normalized `RunOptions`, not raw config/profile inputs.
- Carry the resolved runtime handoff on `StageExecutionRequest` or an
  equivalent typed executor-facing request field, not through untyped metadata.
- Add run-store `runtime.json` write/read APIs and record safe normalized
  runtime metadata during runs as a persisted summary.
- Ensure runtime metadata is excluded from semantic fingerprints.

Out of scope:

- Raw adapter payload persistence, environment key/value persistence, plugin
  discovery, executor-specific command behavior.

Acceptance criteria:

- Runs write schema-versioned `runtime.json`.
- Future workers/executors can receive resolved per-stage runtime API data
  without re-running merge logic or parsing raw CLI/config data.
- Persisted `runtime.json` exposes only safe summaries and excludes environment
  keys/values and raw unvalidated adapter payloads.
- Runtime option changes affect `runtime.json` but not semantic fingerprints.
- Commands remain thin wrappers over public APIs.
- Validate/plan/run consume normalized runtime options where relevant while
  preserving planning/execution boundaries.
- `RunRequest.options` is the canonical runner invocation-policy field after
  normalization; retained overlapping constructor fields fail clearly on
  conflict and are not read as parallel semantics by runner/store/executor
  code.
- Stage execution requests carry typed resolved runtime data.

Test expectations:

- Package: run-store runtime metadata API imports.
- Unit: runtime metadata serialization, resolved per-stage runtime summary
  construction, `RunRequest`/`RunOptions` normalization and conflict handling,
  typed stage execution runtime request validation, run-store read/write.
- Contract: run-store `runtime.json` contract, resolved stage runtime handoff
  contract, `RunRequest.options` invocation-policy contract,
  CLI/config/Python semantic equivalence, and fingerprint non-impact contract.
- Integration: plan/run/preflight wiring where relevant, local run writes
  `runtime.json`, and runner/executor request construction consumes normalized
  `RunOptions`.
- E2E: local synthetic run with profile/resources/tags/notes, ignored-resource
  warnings, and unchanged fingerprints.
- Opt-in: none.

Design impact:

- Completes v4 by making the runtime API observable through real workflows.

Future compatibility:

- Gives run catalog, bundles, sweeps, and future executors a clear runtime
  metadata source plus a per-stage handoff that future stage-worker and adapter
  phases can consume.

Alternatives rejected:

- Status-embedded runtime metadata and ad hoc CLI flag flow.

Debt introduced:

- No raw adapter payload persistence and no environment recording.

Reviewability:

- Review as user-facing wiring and persisted metadata behavior after model and
  descriptor foundations land.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Should v4 optimize primarily for user-facing CLI ergonomics now, executor adapter readiness later, or public Python API stability first? | Roadmap framing and phase order | Public Python API stability first, while keeping CLI/config mapping in scope. | answered |
| Should v4 implementation wait for v3 Phase 4 to merge, or should planning continue while recording that implementation is blocked on the remaining v3 diagnostic phase? | Prerequisites and implementation readiness | V3 implementation is finalized; no v3 planning blocker remains. | answered |
| How should per-stage execution configuration and environment be represented without polluting semantic pipeline specs? | Runtime API, profiles, future executors, provenance | Treat stage-scoped runtime configuration as first-class runtime/profile data resolved against stage IDs after pipeline construction, not as direct `StageSpec` semantics. | answered |
| Is a fixed generic `ResourceRequest` dataclass sufficient, or should v4 introduce a more extensible resource request architecture? | Resource model, executor capabilities, future adapters | Use typed-entry `ResourceRequest(entries={...})` as a hard v4 schema swap; do not support compatibility aliases. | answered |
| How should the executor registry/capability surface be shaped so later adapter-specific and plugin-first support can plug in cleanly? | Executor registry, preflight, CLI/config mapping, plugin roadmap | Define generic registry and capability contracts in v4 without implementing plugin discovery or adapter-specific schemas. | answered |
| What precedence should runtime options use across config, selected profiles, and explicit invocation inputs? | Config/CLI/API mapping and normalization | Config base, selected profile overlay, explicit CLI/API invocation override. | answered |
| How broad should per-stage override matching be in v4? | Runtime profiles, stage validation, future flexibility | Exact stage-id overrides only; defer globs, tags, groups, and pattern matching. | answered |
| How should environment requests be recorded in run metadata/provenance? | Secrets, provenance, runtime metadata, local execution | Do not store environment keys or values by default; allow explicit opt-in selected keys later. | answered |
| Should resource requests avoid first-class fields such as `cpus`, `memory_mb`, and `gpus` in favor of typed entries with per-type validation? | Resource model, compatibility, executor capabilities, future adapters | Use typed-entry `ResourceRequest(entries={...})` as a hard v4 schema swap; do not support compatibility aliases. | answered |
| Should the v4 phase sketch be split into smaller units of work than the initial four phases? | Phase shaping, reviewability, implementation risk | Use a seven-phase split: runtime package boundary, typed resource entries, run options/environment models, runtime profiles/merge semantics, executor descriptors/capability validation, runtime preflight and CLI/config mapping, run workflow/runtime metadata. | answered |

## Handoff Notes

Implementation-plan draft inputs:

- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`, v4
  section.
- Primary planning source:
  `docs/implementation-plans/roadmap-v4-planning-notes.md`.
- Core design direction:
  - Optimize for public Python API stability and design quality first; CLI and
    config leverage the API.
  - Split `loom.pipeline.runtime` into an import-light package/facade with
    focused submodules.
  - Keep planning-owned selector/resume semantics decoupled from runtime.
  - Use `RunOptions` as the public invocation aggregate and canonical
    invocation-policy model. `RunRequest` remains the execution envelope and
    carries normalized `RunOptions` through the runner.
  - Use deterministic precedence: config base < selected profile < explicit
    CLI/API invocation options.
  - Include runtime profiles and exact stage-id `StageRuntimeOptions`.
  - Make environment requests runtime data only in v4; do not apply to local
    in-process execution and do not record environment keys or values.
  - Hard-swap resources to typed `ResourceRequest(entries={...})` with
    `ResourceEntry`; use explicit validator registries; do not support `cpus`,
    `memory_mb`, or `gpus` compatibility aliases.
  - Add structured executor descriptors/capabilities and warnings for ignored
    local resources and unclaimed adapter namespaces.
  - Add runtime/capability preflight checks with stable IDs.
  - Add CLI/config runtime mapping, including `--profile`, `--tag KEY=VALUE`,
    and `--note TEXT`.
  - Persist safe runtime metadata in separate schema-versioned `runtime.json`.
  - Exclude runtime options/resources/profiles/environment/tags/notes/adapter
    options from semantic fingerprints by default.
- Confirmed seven-phase sketch:
  1. Runtime Package Boundary.
  2. Typed Resource Entries.
  3. Run Options And Environment Models.
  4. Runtime Profiles And Merge Semantics.
  5. Executor Descriptors And Capability Validation.
  6. Runtime Preflight And CLI/Config Mapping.
  7. Run Workflow And Runtime Metadata.
- Required docs updates: `docs/structure.md`,
  `docs/features/runtime-resources.md`, `docs/features/pipeline.md`, and any
  CLI/preflight/run-store docs touched by implementation-plan phase scopes.
- Required test posture: package, unit, contract, integration, and e2e coverage
  as recorded in the phase sketch; no opt-in external-system tests.

Plan-quality-gate risks:

- V4 touches public runtime/resource APIs, CLI/config mapping, diagnostics,
  executor resolution, and future executor compatibility. The implementation
  plan will likely need expanded-path depth and careful phase boundaries.
- Runtime profile and option precedence decisions could create durable public
  behavior if not settled before drafting the implementation plan.
- `RunOptions` must not become a parallel model beside execution `RunRequest`;
  v4 needs one canonical invocation-policy path into runner and stage execution
  requests.
- Executor registry design must avoid pre-implementing plugin discovery or
  future executor behavior.
- Per-stage runtime override design must avoid becoming a second pipeline spec
  or an implicit pattern language before exact stage-id behavior is stable, but
  should still leave an in-memory resolved per-stage runtime handoff for later
  stage-worker and executor phases while persisting only safe summaries.
- Environment provenance must avoid accidental secret disclosure; opt-in key
  recording needs explicit policy and tests.
- The resource schema refactor is intentionally breaking. The implementation
  plan must scope source/test/docs migration carefully, define resource-kind
  validator and unknown-kind behavior, and make the absence of
  `cpus`/`memory_mb`/`gpus` compatibility aliases explicit.
- Runtime and resource preflight checks must update exact preflight group,
  stable-check-ID, JSON-shape, and strict-mode contracts.

Assumptions to carry forward:

- V4 should treat the v3 diagnostics/preflight surface as available based on
  the user's confirmation that v3 implementation is finalized.
- Per-stage execution configuration and environments are expected first-class
  requirements, but should be designed to preserve pipeline spec portability.
- Resource and executor abstractions must prioritize future extension without
  turning v4 into early SLURM, container, retry, timeout, or plugin
  implementation.
