# Roadmap Stage 13 Planning: Deterministic Sweeps

## Metadata

- Roadmap stage: v13
- Source roadmap: `docs/roadmap.md`
- Previous version status: `docs/roadmap/stage-12/planning.md` is confirmed and
  `docs/roadmap/stage-12/implementation-plan.md` has passed its plan quality
  gate with five pending phases. V13 planning should preserve the v12 boundary
  that sweeps remain ordinary runs inspectable/exportable by run-catalog and
  bundle tools; implementation-plan drafting can proceed from the finalized v12
  plan assumptions, and phase execution must recheck any landed v12 APIs before
  coding against them.
- Planning artifact status: final planning confirmed
- Current discussion stage: implementation-plan quality gate passed
- User phase approval: approved on 2026-05-14 for the five-phase
  implementation shape in `docs/roadmap/stage-13/implementation-plan.md`.
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed by recorded checkpoint; reload notes before design agreement
  - Design agreement review: confirmed
  - Design safety review: completed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: confirmed
  - Handoff: ready
- Related implementation plan: `docs/roadmap/stage-13/implementation-plan.md`
- Related feature docs:
  - `docs/features/sweeps.md`
  - `docs/features/config.md`
  - `docs/features/pipeline.md`
  - `docs/features/execution.md`
  - `docs/features/run-store.md`
  - `docs/features/run-catalog.md`
  - `docs/features/artifacts.md`
  - `docs/features/provenance.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
- Blockers:
  - None for roadmap-stage planning.
  - None from design-safety review.
  - None for implementation-plan drafting.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V13 goal is deterministic sweeps: grid/manual expansion, manifests, sequential execution, status, collection, and `loom sweep` CLI commands. | roadmap scope | Baseline v13 must keep each trial an ordinary Loom run. |
| `docs/roadmap.md` | V13 defers bounded local concurrency, distributed controllers, SLURM per-trial batch submission, failed-trial rerun policies, random search, Bayesian optimization, adaptive generation, early stopping, and domain-specific result aggregation. | scope boundaries | User wants to explore Optuna and optimizer-style integrations; planning should define generic interfaces/adapters without pulling adaptive optimization into v13 core unless explicitly accepted. |
| `docs/features/sweeps.md` | `loom.pipeline.sweep` sits above config composition and pipeline execution, owns sweep specs, expansion, trial records, orchestration, status, and collection. | package ownership | Strong source for domain-neutral sweep boundaries. |
| `docs/features/sweeps.md` | Sweep layer should not implement config merge, stage execution, scheduler submission, domain metrics, or Bayesian optimization. | non-goals | Supports adapter-first design for external sweep providers. |
| `docs/features/sweeps.md` | Planned package shape includes `spec.py`, `grid.py`, `manual.py`, `trials.py`, `runner.py`, and `errors.py`. | likely module layout | May need expansion/adapters/protocol modules if planning locks a generic provider interface. |
| `docs/features/config.md` | Config composition explicitly avoids Hydra-style launchers/sweepers and owns override parsing/merge semantics. | config boundary | Sweeps should create or pass ordinary overrides through existing config APIs. |
| `docs/features/cli.md` | CLI expects `loom sweep plan`, `loom sweep run`, and `loom sweep status` after sweep APIs exist. | CLI surface | Roadmap also includes basic `collect`; planning should settle command naming and output modes. |
| `docs/structure.md` | Target tree reserves `src/loom/pipeline/sweep/`; dependency direction places sweeps above planning/execution/stores and below CLI. | source-tree boundary | Confirms sweeps as pipeline-owned and CLI-thin. |
| `docs/loom.md` | Loom stays domain-neutral; project code owns metrics, models, reports, and analysis behavior. | product boundary | Collection must avoid metric semantics unless project code exposes plain data. |
| `docs/GLOSSARY.md` | Use `run_uri`, distinguish run catalog from authority, status from planner action, and keep domain nouns out of generic APIs. | vocabulary | Sweep trial records should use `run_uri` and persisted status terms consistently. |
| `src/loom/pipeline/stores/coordination.py` | `WorkspaceCoordinationStore`, `SweepIdentity`, `TrialReference`, `TrialState`, and trial/resource lease records already exist. | existing foundation | V13 can reference coordination for future concurrent/adaptive controllers without making v13 sequential sweeps database-first. |
| `src/loom/pipeline/execution/models.py` and `runner.py` | `RunRequest` carries config/pipeline, run URI, options, selectors, resume, command, failure policy, and metadata; `PipelineRunner` owns one run. | execution integration | Sweep runner should construct ordinary `RunRequest` values and delegate execution. |
| `src/loom/config/overrides.py` | Override parsing supports dot paths, update/add operations, plain-data JSON values, and redaction-aware provenance. | override generation | Sweep-generated overrides should use existing override syntax/helpers, not a second merge language. |
| `src/loom/queue/service.py` and `src/loom/queue/models.py` | Queue service enqueues whole-run intents with launch contracts and run metadata. | future queued sweep path | Future sweep submission can adapt trials into queue items instead of creating a separate scheduler path. |
| `src/loom/runs/catalog.py` and `src/loom/runs/models.py` | Run catalog lists/compares metadata-only run summaries and artifact summaries over a run collection. | status and collection | Sweep status/collection should consume run summaries or store read models rather than duplicating catalog truth. |
| `docs/roadmap/stage-12/planning.md` | V12 planning expects sweeps to remain ordinary runs that bundle tools can inspect, not a parallel export format. | adjacent roadmap dependency | V13 planning must preserve bundle/catalog compatibility. |
| `docs/roadmap/stage-12/implementation-plan.md` | V12 plan quality gate passed; v12 defines adapter-neutral portable-run exchange records, local bundle adapters, offline-evidence alignment, importer/exporter protocols, and `loom runs export/inspect/import` as future phase work. | adjacent implementation dependency | V13 should treat v12 as a finalized design plan but not assume v12 phase APIs have landed until phase execution rechecks current code. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, roadmap v13 section, roadmap feature-doc table | The workflow requires staged discussion, source-backed briefing, agreement queues, design-safety review, and no implementation-plan draft until planning is confirmed. | None for startup. |
| Feature docs | `sweeps.md`, targeted `config.md`, `cli.md`, `loom.md`, `structure.md`, `GLOSSARY.md`, plus run-catalog, artifacts, plugins, protocols, remote-stores, reliability, and testing docs for design-safety/validation | Feature docs define ordinary-run sweep semantics, deterministic expansion, manifest layout, generic collection, deferred adaptive optimization, explicit plugin discovery, metadata-only catalog/export boundaries, and local deterministic testing. | None for planning; implementation phases should recheck feature docs touched by their scope. |
| Source and tests | `src/loom/pipeline/stores/coordination.py`, `src/loom/pipeline/execution/models.py`, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/execution/lifecycle.py`, `src/loom/pipeline/stage.py`, `src/loom/config/overrides.py`, `src/loom/queue/*`, `src/loom/runs/*`, `src/loom/cli/main.py`, sweep-related tests via `rg` | Coordination, queue, run catalog, config override, runner, stage contract, lifecycle, and CLI seams exist; `src/loom/pipeline/sweep/` does not. | None for planning; implementation phases should inspect exact current APIs before editing. |
| Prior or adjacent plans | `docs/roadmap/stage-12/planning.md`, `docs/roadmap/stage-12/implementation-plan.md`, v10/v11 implementation references to sweep/coordination | V10/v11 already created authority-backed workspace/sweep coordination; v12 planning is confirmed and its implementation plan passed the quality gate with pending phases. | V13 phase execution must recheck which v12 APIs have actually landed before depending on bundle/export code. |

## Roadmap Extraction

Baseline roadmap outcome:

- Users can define grid or manual sweeps, inspect deterministic planned trials,
  execute trials sequentially through normal Loom run execution, view aggregated
  trial status, and collect generic artifact refs or simple metadata.
- Every trial remains an ordinary run with a normal `run_uri`, run directory,
  run-store state, provenance, artifacts, and catalog visibility.
- Sweep logic delegates config composition, stage execution, scheduler behavior,
  resume, artifact persistence, and catalog truth to existing Loom subsystems.

Prerequisites:

- Config composition, overlays, and override parsing from v0/v1/v2.
- Pipeline planning and `PipelineRunner` single-run execution.
- Authority-backed run-store lifecycle and local materialization semantics.
- Run catalog metadata inspection from v8 and v12 bundle/export compatibility.
- Workspace/sweep coordination primitives from v9/v10 for later non-sequential
  controllers, even if v13 sequential sweeps can start manifest-first.
- Queue whole-run dispatch from v11 as a future submission adapter target, not a
  required v13 execution path unless planning selects it.

Primary feature docs:

- `sweeps.md`
- `config.md`
- `pipeline.md`
- `execution.md`
- `run-store.md`
- `run-catalog.md`
- `artifacts.md`
- `provenance.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Bounded local concurrency.
- Distributed sweep controllers.
- SLURM per-trial batch submission.
- Failed-trial rerun policies beyond normal run resume.
- Random search, Bayesian optimization, adaptive generation, and early stopping.
- Domain-specific metric/result aggregation.
- Optional third-party optimizer dependencies in core.
- Treating sweep state as a replacement for run-store or catalog truth.

Future-roadmap touchpoints:

- V14 plugin discovery can later load external sweep providers, optimizers, or
  collectors after the v13 protocol shape exists.
- V15/V16 external artifact interfaces and payload materialization should be
  able to preserve sweep/trial artifact refs without sweep-specific payload
  semantics.
- V19 reliability may add retry, timeout, and event-sink behavior that sweeps
  should consume through normal run/runtime interfaces.
- Later queue, SLURM, or distributed-controller work should adapt trial run
  intents through generic trial-provider/submission interfaces instead of
  rewriting expansion semantics.

Compatibility obligations:

- Trial IDs, order, run directories, and override generation must be stable.
- Persisted sweep/trial manifests must be versioned, plain-data, and
  inspectable without project code imports.
- Python APIs and CLI output must make failed trials visible without erasing
  successful trial evidence.
- Collection must stay metadata/artifact-ref oriented unless project code or a
  future adapter explicitly provides typed plain-data results.
- External providers such as Optuna should be future consumers of generic trial
  suggestion/result interfaces, not hard dependencies or semantic owners of
  Loom core.

## Stage Briefing

What this stage is:

- V13 is Loom's first sweep version. It turns one base experiment into a
  deterministic collection of normal Loom runs. The initial shape is grid and
  manual trial expansion, plan-only inspection, sequential run execution, status
  aggregation, generic result collection, manifests, and a `loom sweep` CLI
  group.

Why this stage exists:

- Users need a generic way to run repeated ablations and small parameter
  explorations without copying whole configs or writing one-off project loops.
- Earlier stages gave Loom config composition, run execution, run stores, run
  catalogs, queue foundations, and bundle/export compatibility. V13 should tie
  those pieces together while preserving their ownership boundaries.
- The user specifically wants extra time on functionality and behavior, with
  expectation alignment before implementation planning, and wants the design to
  leave room for Optuna or similar sweep/optimizer providers.

Impacted or linked work:

- `loom.config` supplies override parsing and composition. Sweeps should
  generate ordinary override values or strings, not implement merge semantics.
- `loom.pipeline.execution` supplies `PipelineRunner` and `RunRequest`.
  Sweeps should delegate one trial as one normal run.
- `loom.pipeline.stores` already owns workspace/sweep coordination primitives.
  V13 should decide when sequential sweeps are manifest-only and when they
  record coordination facts.
- `loom.runs` supplies catalog summaries and artifact metadata. Sweep status
  and collection should align with these records.
- `loom.queue` can eventually dispatch trials as whole-run intents. V13 should
  leave a path for that adapter without requiring queue execution by default.
- `loom.cli` will expose thin sweep commands over Python APIs.

Likely public surfaces and durable artifacts:

- `SweepSpec`, manual trial spec, generated `TrialSpec`, sweep plan/result
  models, trial result/status summaries, collection result models, and
  sweep-specific errors.
- A small generic protocol layer may be needed for trial generation and external
  provider adaptation, such as deterministic providers, manual providers, and
  future optimizer-backed providers. The exact shape is not locked yet.
- Versioned `sweep.json` and `trials.json` manifests, optional human-readable
  CSV, and copied authored sweep spec under the sweep root.
- CLI commands likely include `loom sweep plan`, `loom sweep run`,
  `loom sweep status`, and `loom sweep collect` with JSON/text output.
- Trial run metadata/provenance should include sweep name/id, trial id/index,
  override facts, trial metadata, and provider/strategy facts when available.

Structure rationale:

- The roadmap intentionally puts deterministic sweeps after catalogs, authority,
  queues, and bundles because sweeps should orchestrate many existing run
  primitives instead of creating a parallel runtime.
- The first implementation should be deterministic and sequential because that
  makes IDs, manifests, validation, CLI behavior, and status semantics
  reviewable before adding concurrency or adaptive control.
- A generic provider/adapter boundary can be planned now even if v13 ships only
  built-in grid/manual providers. This is the clean path for later Optuna-like
  integration without importing Optuna or accepting adaptive optimization
  semantics prematurely.

Visible assumptions, risks, and constraints:

- The existing feature doc calls the first sweep scope "v0"; in roadmap terms
  this is v13. Planning should translate that document into roadmap-stage
  phases without changing the product vocabulary.
- V12 planning and implementation planning are confirmed, but v12 phase APIs
  may still be pending. V13 must preserve the assumption that trial runs are
  ordinary runs that bundle/export/catalog tooling can inspect.
- The biggest product risk is mixing deterministic expansion with adaptive
  optimization. If external optimizer support is desired, the interface should
  likely model trial providers/adapters and result feedback separately while v13
  core remains deterministic by default.
- The biggest architecture risk is giving sweeps their own scheduler, config
  merge semantics, store truth, or metric language. Those would conflict with
  existing Loom boundaries.
- The biggest compatibility risk is freezing a too-narrow manifest/API that
  cannot later represent provider identity, external suggestion IDs,
  intermediate states, result feedback, queue dispatch handles, or plugin-loaded
  providers.

User clarification questions and resolved answers:

- User wants the adapter/interface shape designed first. V13 should define a
  generic sweep adapter/provider interface, then implement Loom's deterministic
  grid and manual sweep behaviors as first-party adapters. Future providers
  such as Optuna should be able to slot into the same adapter shape later.
- User confirmed concrete Optuna support should be deferred for now, while
  focusing v13 on a robust and flexible interface/adapter design that makes
  future integration straightforward.
- User wants an adaptive feedback protocol defined now because it is likely to
  be useful for future providers. User also wants early stopping procedures
  considered now because they may save substantial run time.
- User clarified early stopping should be cooperative while something is
  running. V13 should provide a generic public policy/interface and a
  stage-integrated signal, for example a dedicated early-stopping exception or
  result signal that stages can raise or return when downstream project logic
  decides to stop. User prefers this to executor-side killing, because it avoids
  Loom needing to understand downstream metric semantics. V13 should not
  support cancelling already scheduled trials for now.
- User wants the adapter interface to be a stable public contract immediately,
  used by Loom's own grid/manual implementations and future external provider
  integrations.
- User agreed with the recommended early-stop status mapping: v13 should define
  a stable cooperative early-stop signal and structured reason code, then map
  controlled pruning/stopping onto the existing `CANCELLED` lifecycle state.
  Sweep/trial presentation may expose a semantic early-stopped outcome derived
  from `CANCELLED` plus `reason.code == "early_stop"`, but core run/stage
  status should not add `EARLY_STOPPED` or a generic `STOPPED` value.
- User confirmed sequential sweeps should run remaining trials after a failed
  trial, record failures, and return an overall failed sweep result.
- User confirmed v13 should support explicit resume against compatible existing
  sweep manifests while deferring richer rerun/filtering features such as
  failed-only reruns, from-trial selection, and retry policies.
- User confirmed collection should start with trial facts, override values,
  run status, and artifact refs/metadata, not default metric payload parsing.
  V13 should still define an artifact-extraction interface with explicit
  unsupported/not-implemented behavior for future extraction adapters.
- User confirmed v13 should always record sweep/trial coordination facts
  whenever an authority-backed runtime is used. Manifests remain the durable
  sweep artifacts, but authority-backed runs should also create or update
  `SweepIdentity` and `TrialReference`-style coordination records.
- User selected a default generated-trial guard of `100` for v13. Larger
  generated sweeps should require an explicit spec/CLI override.
- User agreed with index-based stable trial IDs and asked whether those should
  link to `run_uri`. Planning answer: keep `trial_id` separate as the stable
  sweep-local identity, derive or associate `run_uri` from it through run-root
  policy, and persist the mapping in manifests and coordination records.
- User wants a generic base adapter/provider interface that naturally handles
  both finite planned trial sets and future incremental/adaptive generation.
  The design should start from a stream/proposal-style interface and layer
  finite-count/materialization capabilities on top only when they are available,
  rather than requiring every provider to support `len()`.
- User clarified that when trials are being managed through queue/controller
  infrastructure, Loom should submit trial run intents to the queue controller
  / authority coordination path to keep execution cohesive. User agreed v13
  should include queue-backed trial dispatch as a first-class dispatch adapter
  when queue service/config is provided, while retaining direct sequential
  `PipelineRunner` execution for no-queue local use.
- User confirmed the primary v13 workflow should optimize for finite sweep
  planning: plan, inspect, then run or queue with predictable artifacts and
  status. Future adaptive providers should reuse the same interfaces, while v13
  user experience stays reviewable.
- User confirmed queue-backed dispatch should enqueue all finite planned trials
  and rely on `loom sweep status` to aggregate progress from run, queue, and
  coordination state. V13 should not make the sweep runner a long-running queue
  controller.
- User confirmed early-stopped trials should count separately in sweep summaries
  as a derived outcome such as `early_stopped`, while the underlying lifecycle
  remains `CANCELLED` with `LifecycleReason(code="early_stop")`.

## User Intent

Target audience:

- Researchers and operators who need repeatable ablations and small
  hyperparameter explorations over Loom pipelines.
- Maintainers and downstream projects that may later adapt external sweep or
  optimization systems such as Optuna without coupling Loom core to them.

User-visible outcome:

- Confirmed: a user can author a sweep spec, inspect the exact trials, run them
  sequentially, see trial statuses, and collect generic artifact/metadata
  summaries.
- Confirmed: the built-in deterministic grid and manual behaviors are presented as
  first-party sweep adapters behind the same generic interface future providers
  will use.
- Confirmed: external optimizer compatibility is planned through generic interfaces
  and adaptive feedback contracts, but concrete Optuna support is deferred.

Success criteria:

- Confirmed: deterministic trial order and IDs are stable.
- Confirmed: each trial is a normal run with normal config/run-store/catalog/bundle
  behavior.
- Confirmed: manifests explain what was expanded and what ran.
- Confirmed: failure/status behavior is predictable and visible.
- Confirmed: adapter/protocol shape is robust enough for Optuna-like providers,
  adaptive feedback, early-stopping policy hooks, and queue dispatch later
  without making them core dependencies.
- Confirmed: early-stopping tools let stage or run code implement arbitrary
  downstream stopping procedures while Loom records a generic controlled
  early-stop outcome.

Non-goals:

- Confirmed: no domain metric semantics in core.
- Confirmed: no hard dependency on Optuna, Ray Tune, W&B, MLflow, DVC, Hydra
  sweepers, or other third-party optimizers.
- Confirmed: no concrete external optimizer adapter in v13.
- Confirmed: no adaptive trial generation as default built-in behavior unless later
  planning explicitly accepts that scope.
- Confirmed: no sweep-owned scheduler or run-store replacement.

Constraints:

- Keep Loom domain-neutral.
- Treat authored sweep configs as trusted project code.
- Preserve source-tree and import-boundary guidance from `docs/structure.md`.
- Ask small batches of high-impact questions, but keep a richer question queue
  visible in this planning artifact per the user's request for deeper alignment.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- V13 should be adapter/interface-first. Built-in deterministic grid and manual
  sweeps should be implemented as first-party adapters behind a generic sweep
  adapter/provider interface.
- Concrete Optuna support is deferred. V13 should nevertheless design a robust,
  flexible adapter surface that can integrate Optuna or other sweep/optimizer
  providers later without changing core trial/run semantics.
- V13 should define an adaptive feedback protocol now. Early stopping must be
  considered now through the confirmed cooperative signal/reason contract.
- Early stopping should be cooperative, not executor-forced by default. Stages
  or run code can integrate a generic public policy/interface and signal
  early-stop intent themselves. V13 should not cancel scheduled trials.
- Cooperative early stopping maps to existing lifecycle status: active stage and
  run cancellation use `CANCELLED` with structured `LifecycleReason` code
  `early_stop`; downstream stage disposition should be represented through
  existing skipped/blocked status plus the same reason where applicable; sweep
  trial outcome may render this as `EARLY_STOPPED`.
- The sweep adapter/provider interface should be a stable public contract in
  v13, not merely an internal or one-cycle provisional seam.
- Sequential sweeps should continue after failed trials by default, then return
  an overall failed sweep result if any required trial failed.
- Resume is explicit and compatibility-checked in v13; richer filtering,
  failed-only reruns, and retry policy are deferred.
- Collection is metadata/artifact-ref first. Artifact payload extraction should
  have a generic interface and explicit unsupported behavior, but no default
  domain metric parsing or implemented extraction adapter is required in v13.
- When an authority-backed runtime is used, v13 should automatically record
  sweep/trial coordination facts in addition to writing manifests.
- Generated adapters should use `100` as the default max-trials guard unless a
  user explicitly raises it.
- Stable default trial IDs are index-based (`trial_0001`, etc.) and remain
  separate from `run_uri`; manifests and coordination records bind each
  `trial_id` to its concrete `run_uri`.
- The stable public adapter/provider contract should support both finite trial
  materialization and future incremental proposal streams, with optional
  finite/count capabilities rather than a mandatory length contract.
- Trial dispatch should be a separate adapter boundary from trial generation.
  V13 includes direct sequential dispatch and queue-backed dispatch when queue
  configuration/service is supplied.
- V13 primary workflow is finite, inspectable planned sweeps that can then be
  run directly or queued. Adaptive interfaces are designed now but default UX
  remains reviewable and finite.
- Queue-backed dispatch enqueues all finite planned trials and leaves ongoing
  queue control to the queue service/controller; `loom sweep status` aggregates
  progress.
- Sweep summaries count early-stopped trials separately from generic
  cancellations, derived from `CANCELLED` plus `early_stop` reason.

Intent discovery locked decisions:

- Target audience: researchers/operators running repeated Loom experiments and
  maintainers/downstream projects that need future external sweep provider
  integration.
- Planning priority: robust stable public adapter/provider and dispatch
  interfaces, while keeping v13 domain-neutral and default behavior
  deterministic and inspectable.
- V13 should optimize for cohesive authority/queue integration where available,
  without requiring queue service for simple local use.
- Primary user workflow: plan a finite sweep, inspect it, then run or queue it
  with predictable manifests, coordination facts, trial status, and collection
  outputs.
- Queue operational boundary: sweep APIs submit finite planned trials when queue
  dispatch is selected, but queue service/controller owns ongoing dispatch
  lifecycle. Sweep status aggregates rather than controlling the queue loop.

Capability triage and candidate-functional-requirement readback:

- Confirmed. Core include/defer decisions are recorded in the capability and
  requirement tables. Remaining work is behavior-baseline readback, examples,
  validation obligations, then design agreement.

Functionality-agreement readback:

- Confirmed requirement baseline: v13 is stable-public-interface-first; built-in
  grid/manual adapters produce finite planned trials; direct sequential and
  queue-backed dispatch execute or enqueue those trials; authority-backed
  runtimes record coordination facts; status and collection are metadata-first;
  cooperative early stop maps to `CANCELLED` plus `early_stop` reason and a
  derived `early_stopped` sweep outcome; concrete external optimizers, default
  adaptive generation, scheduler-specific submission, rich rerun/filtering, and
  artifact payload extraction are deferred.

Functionality and behavior confirmation readback:

- Confirmed. V13 behavior baseline is finite, inspectable sweep planning by
  default, with a stable public adapter/provider interface that can later
  support incremental providers. Built-in grid/manual adapters produce stable
  sweep-local `trial_id` values, bind them to concrete `run_uri` values in
  manifests and coordination records, enforce default max generated trials
  `100`, and produce ordinary Loom run requests. Users can run directly,
  dispatch finite planned trials through a queue-backed adapter when queue
  service/config is supplied, inspect progress with sweep status, and collect
  trial facts plus artifact refs/metadata. Authority-backed runtimes also record
  sweep/trial coordination facts. Failures run remaining trials and fail the
  overall sweep result. Explicit compatible resume is included; rich rerun,
  retry, filtering, concrete optimizers, default adaptive generation,
  scheduler-specific submission, scheduled-trial cancellation, executor-forced
  early stopping, and implemented artifact extraction are deferred. Cooperative
  early stop is a stable stage/run-integrated signal mapped to `CANCELLED` plus
  `LifecycleReason(code="early_stop")`, with a derived `early_stopped` sweep
  outcome.

Design-agreement follow-up:

- Confirmed. The design pass reloaded the checkpoint, preserved the confirmed
  behavior baseline, and resolved the dependency-aware design-agreement queue.
  Repo-supported boundaries are recorded as recommendations or auto-approved
  candidates. The remaining workflow focus is design-safety review.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Adapter/interface-first shape; grid/manual are first-party adapters; concrete Optuna deferred; adaptive feedback protocol included; cooperative early-stop signal/interface included; early stop maps to `CANCELLED` plus `early_stop` reason; adapter contract public/stable; run remaining trials after failure; explicit compatible resume only; metadata-first collection with future extraction interface; authority-backed runtimes record sweep/trial coordination facts; default generated-trial guard `100`; `trial_id` separate from `run_uri`; adapter interface supports finite and incremental providers; queue-backed dispatch adapter included when queue config/service is supplied | Keep deterministic ordinary-run behavior as v13 default; design future-provider compatibility deliberately; no scheduled-trial cancellation; no new `EARLY_STOPPED`/`STOPPED` core status; no rich failed-only reruns; no default metric extraction; no mandatory provider `len()`; direct sequential dispatch remains available for no-queue local use | None for roadmap framing | Intent discovery and functionality agreement |
| Intent discovery | Target audience, planning priority, finite plan/inspect/run-or-queue workflow, queue operational boundary, and early-stop visibility recorded | Interface robustness and future provider compatibility are first-order goals; sweep status aggregates queue progress rather than controlling the queue loop | None at intent level | Behavior baseline confirmation |
| Capability triage and candidate functional requirements | Include/defer decisions recorded for core capabilities | Built-in v13 consumes finite planned trial sets; future providers can be incremental | Exact artifact-extraction and dispatch interface details remain design-stage work | Behavior baseline confirmation |
| Functionality agreement review | FRQ-1 through FRQ-16 confirmed | Requirements FR-1 through FR-10 established as confirmed baseline | None at requirement level | Behavior baseline confirmation |
| Functionality and behavior confirmation | Confirmed behavior baseline matches FR-1 through FR-10 and all answered open questions | Finite plan/inspect/run-or-queue workflow, stable public interfaces, metadata-first collection, cooperative early stop, explicit compatible resume | None | Context checkpoint |
| Context compaction/reset checkpoint | Checkpoint recorded in this artifact | Reload planning artifact and design-agreement prompt before design pass; do not reopen confirmed behavior unless user explicitly asks | None | Design agreement review |
| Design agreement review | Source-tree boundary, queue/dispatch separation, manifest-plus-coordination persistence, metadata-first collection, status derivation, contextful provider/proposal protocol, and cooperative early-stop signal/helper shape recorded as design defaults | Explicit provider protocol with optional finite capabilities and separate feedback hook; `context.stop_early(...)` ergonomic API backed by typed signal primitive | None | Design-safety review |
| Design safety review | Passed with no blockers; recorded recommendations for provider protocol minimality, early-stop lifecycle ordering, queue dispatch ownership, v12 compatibility, and unsupported extraction | Keep seams plain-data, contract-tested, and plugin/provider-free in v13 | None | Examples and validation confirmation |
| Examples and validation strategy | Examples and validation matrix confirmed; default validation local, synthetic, deterministic, and domain-neutral | No Optuna, network, remote service, real cluster, or downstream project package in default tests | None | Phase shaping |
| Phase shaping | Five-phase sketch confirmed: contracts/manifests; grid/manual planning; early-stop/direct dispatch; coordination/queue/status; collection/CLI hardening | Public contracts before dependent behavior; early-stop lifecycle before derived status; v12 API recheck before compatibility claims | None | Implementation readiness |
| Implementation readiness | Confirmed; no unresolved functionality/design blockers remain | Implementation-plan drafting may proceed from this artifact | None | Handoff |
| Handoff | Ready | Confirmed planning artifact is the implementation-plan source of truth | None | Implementation-plan draft |

## Capability Triage

Confirmed include/defer decisions.

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Grid sweep expansion | include | Roadmap baseline and deterministic core behavior. | Needs trial ordering and count-limit behavior. |
| Manual trial expansion | include | Roadmap baseline and useful bridge for external tools generating explicit trials. | May be the first adapter target. |
| Stable trial IDs and run directories | include | Required for reproducibility, manifests, status, bundles, and tests. | Needs naming policy. |
| Trial count safety guard | include | User selected default generated-trial guard of `100`. | Explicit override required for larger generated sweeps. |
| Sweep and trial manifests | include | Required for inspectability and compatibility. | Should be versioned plain data. |
| Plan-only mode | include | Required exit criterion. | Must detect existing incompatible manifests. |
| Sequential execution through `PipelineRunner` | include | Roadmap baseline; keeps trial runs ordinary. | Failure policy needs user alignment. |
| Status aggregation | include | Roadmap baseline. | Should read run-store/catalog-compatible metadata. |
| Generic result collection | include | Roadmap baseline. | Start with artifact refs and simple metadata, not metrics. |
| Generic artifact extraction interface | include | User wants an interface for artifact extraction, with unsupported/not-implemented behavior for now. | Keep default collection metadata-only; no core metric parsing. |
| `loom sweep` CLI | include | Roadmap baseline. | CLI should remain thin over Python APIs. |
| Generic sweep adapter/provider interface | include | User explicitly wants the interface designed first, with grid/manual implemented as first-party adapters and future providers slotted into the same shape. | Design must stay generic and domain-neutral. |
| Concrete Optuna adapter | defer | User confirmed concrete Optuna support should be deferred while v13 focuses on robust adapter design. | Future plugin/provider work can add a real adapter. |
| Adaptive feedback protocol | include | User wants the protocol defined now because future providers will need result feedback. | Must separate protocol definition from concrete adaptive optimizer behavior. |
| Cooperative early stopping procedure hooks | include | User wants a generic policy/interface and stage-integrated signal so project code can stop itself while running without Loom understanding metrics. | Map controlled run/trial pruning to `CANCELLED` plus `LifecycleReason(code="early_stop")`; no new core status. |
| Adaptive trial generation loop | defer / maybe | Needed for real optimizers, but conflicts with deterministic baseline if included too early. | Current default is protocol-ready but no default adaptive optimizer. |
| Queue-backed trial dispatch | include | User wants queue/controller-backed trial submission when queue config/service is provided to keep trial execution cohesive. | Direct sequential dispatch remains available for no-queue local use. |
| Authority-backed sweep/trial coordination records | include | User wants sweep/trial coordination facts recorded whenever an authority-backed runtime is used. | Manifests remain durable artifacts; coordination records support future concurrency/distribution. |
| Incremental/adaptive provider-capable base interface | include | User wants one generic base interface that can handle finite planned sets and future generated trials, with optional finite capabilities. | Built-in v13 execution still consumes a finite planned set. |
| SLURM per-trial submission | defer | Explicitly deferred by roadmap. | Existing executor config still applies inside each ordinary trial run. |
| Failed-trial rerun policy | defer / maybe | Roadmap defers failed-trial rerun policies; normal run resume can be used. | Need clarify if basic resume/status selection belongs in v13. |

## Functionality Agreement Queue

Confirmed functionality-agreement queue.

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | V13 optimization priority: deterministic built-in sweep UX vs generic provider foundation | none | 1 | Design the generic adapter/interface first; implement deterministic grid and manual sweeps as first-party adapters. | Sets scope and phase boundaries. | User answered: adapter/interface-first is preferred. | confirmed |
| FRQ-2 | External optimizer boundary | FRQ-1 | 2 | No concrete Optuna adapter in v13; focus on robust flexible interface/adapters for future integration. | Prevents heavyweight dependency and adaptive behavior creep. | User answered: defer concrete Optuna, but keep future integration easy. | confirmed |
| FRQ-3 | Adaptive feedback and early stopping boundary | FRQ-1 | 3 | Define adaptive feedback protocol now; include cooperative early-stopping policy/interface and stage-integrated early-stop signal; do not implement executor-forced killing or scheduled-trial cancellation in v13. | Affects public protocol shape, manifests, status/result collection, and roadmap deferral policy. | User answered: cooperative early stopping while running is wanted; scheduled-trial cancellation is not. | confirmed |
| FRQ-4 | Adapter API stability | FRQ-1 | 4 | Treat the adapter/provider interface as a stable public v13 contract. | Determines compatibility burden and contract-test requirements. | User answered: stable public contract immediately. | confirmed |
| FRQ-5 | Early-stopped status and outcome mapping | FRQ-3 | 5 | Use existing `CANCELLED` lifecycle state plus structured `LifecycleReason(code="early_stop")`; expose semantic `EARLY_STOPPED` at the sweep/trial outcome or presentation layer when derived from that reason. | Affects run-store, catalog, CLI, status aggregation, and resume behavior. | User agreed with the recommendation; avoids broad lifecycle enum changes while preserving semantic clarity. | confirmed |
| FRQ-6 | Failure policy default | FRQ-1 | 6 | Continue on trial failure, record failed trial, run remaining trials, return failed sweep result when any required trial failed. | Affects user trust and long sweeps. | User answered: run remaining trials. | confirmed |
| FRQ-7 | Existing sweep directory compatibility and resume | FRQ-1 | 7 | Fail on incompatible manifests; allow explicit resume/open-existing for compatible trials using normal run resume; defer rich filtering/rerun features. | Protects reproducibility and rerun behavior. | User agreed: explicit resume but defer richer features. | confirmed |
| FRQ-8 | Result collection scope | FRQ-1 | 8 | Collect artifact refs/metadata and trial facts by default; define a generic artifact-extraction interface with explicit unsupported/not-implemented behavior for now. | Keeps core domain-neutral while leaving future extraction adapters a stable seam. | User agreed: metadata-first collection plus extraction interface, not implemented initially. | confirmed |
| FRQ-9 | Coordination default for sequential v13 | FRQ-1 | 9 | Always record sweep/trial coordination facts whenever an authority-backed runtime is used, while still writing manifests. | Affects store coupling and future concurrency. | User answered: authority-backed runtimes should always record coordination facts. | confirmed |
| FRQ-10 | Generated trial count guard | FRQ-1 | 10 | Default max generated trials is `100`; require explicit override for larger generated sweeps. | Prevents accidental large runs and expensive expansion. | User answered: use `100` for now. | confirmed |
| FRQ-11 | Trial identity and run URI relationship | FRQ-1 | 11 | Keep `trial_id` as stable sweep-local identity and `run_uri` as concrete run address/reference; persist the mapping in manifests and coordination records. | Preserves stable trial identity across run-root changes and keeps run catalog identity clean. | User asked whether trial ID should link to run URI; recommendation is separate but mapped. | confirmed |
| FRQ-12 | Finite and incremental provider interface shape | FRQ-1 | 12 | Design a generic base provider/proposal stream that can support both finite planned sets and future incremental/adaptive trial generation; finite count/materialization is an optional capability, not required of every provider. | Avoids overfitting to grid/manual while still letting v13 execute finite deterministic plans. | User wants an interface that naturally handles both, with natural split only if needed. | confirmed |
| FRQ-13 | Trial dispatch adapter boundary | FRQ-1 | 13 | Include direct sequential dispatch and queue-backed dispatch as first-class dispatch adapters; queue-backed dispatch submits finite planned trials to queue controller when queue service/config is supplied. | Keeps sweep execution cohesive with authority/queue infrastructure without forcing queue service for local use. | User agreed with queue-backed dispatch when queue config/service exists. | confirmed |
| FRQ-14 | Primary workflow priority | FRQ-1 | 14 | Optimize v13 for finite plan/inspect/run-or-queue workflows with predictable artifacts and status; future adaptive providers reuse the same interfaces. | Keeps initial UX reviewable while preserving extensibility. | User agreed. | confirmed |
| FRQ-15 | Queue-backed operation boundary | FRQ-13 | 15 | Queue dispatch enqueues all finite planned trials, then `loom sweep status` aggregates progress from run, queue, and coordination state; sweep runner does not become a queue controller. | Preserves ownership between sweep orchestration and queue service/controller. | User agreed. | confirmed |
| FRQ-16 | Early stopping summary visibility | FRQ-5 | 16 | Count early-stopped trials separately in sweep summaries while underlying run lifecycle remains `CANCELLED` with `early_stop` reason. | Makes user output clear without lifecycle enum churn. | User agreed. | confirmed |

## Functional Requirements

Confirmed functional requirements.

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Deterministic sweep planning | none | Expand grid/manual specs into stable ordered `TrialSpec` values with a default generated-trial guard of `100`. | Reproducibility and inspectable sweep runs; prevents accidental large sweeps. | Built-in grid/manual adapters; larger generated sweeps require explicit max-trials override. | `loom sweep plan` shows trial count, IDs, overrides, and warnings or guard failures. | Pure expansion functions produce deterministic plans and enforce max-trial policy. | Unit/contract tests for ordering, IDs, override facts, and count guard behavior. | confirmed |
| FR-2 | Manifest-backed sweep run | FR-1 | Write versioned sweep/trial manifests and run each trial as ordinary run. | Durable inspection and catalog/bundle compatibility. | Sequential by default. | `loom sweep run` prints summary and leaves normal trial run dirs. | Construct `RunRequest` per trial and delegate to `PipelineRunner`. | Integration tests with fake/minimal runner. | confirmed |
| FR-3 | Status aggregation | FR-2 | Summarize statuses across trial runs. | Users need failed/running/succeeded visibility. | Read persisted state, not project code. | `loom sweep status` shows counts and failed trials. | Read manifests plus run-store/catalog-compatible summaries. | Synthetic run-store/catalog tests. | confirmed |
| FR-4 | Generic collection | FR-2 | Collect trial override facts plus artifact refs/metadata by default and expose a future artifact-extraction interface with unsupported behavior. | Users need results table without core metric semantics; future adapters need a stable extraction seam. | Metadata/artifact refs in v13 default; extraction interface only, no implemented metric/payload parser. | `loom sweep collect` writes table/JSON/CSV of trial facts and artifact refs; unsupported extraction requests fail explicitly. | Use artifact summaries and stable trial facts; extraction interface returns structured unsupported/not-implemented diagnostics. | Contract tests for JSON/CSV shape and unsupported extraction behavior. | confirmed |
| FR-5 | Sweep adapter/provider foundation | FR-1 | Define a stable public generic adapter/provider shape and implement grid/manual as first-party adapters. | Prevents deterministic sweep code from becoming a dead-end special case. | Public Python interface for v13 planning, expansion, and future adapters; base interface supports proposal streams, with finite count/materialization as optional capabilities. | Built-in grid/manual behavior works through the same conceptual adapter surface future providers use. | Provider identity, generated trial proposals/specs, metadata, compatibility facts, and optional finite-planning capabilities are represented as plain data. | Contract tests for built-in adapters, provider metadata, finite capability behavior, and no mandatory `len()` assumption; design-safety review. | confirmed |
| FR-6 | Adaptive feedback protocol | FR-5 | Define the generic result-feedback shape future adaptive providers can consume. | Optuna-like providers need trial observations/results without Loom understanding domain metrics. | Protocol and persisted metadata shape; concrete adaptive provider deferred. | No concrete optimizer is shipped, but the API/manifest shape can carry feedback-compatible facts. | Trial result/status/artifact metadata can be reported through a generic feedback contract. | Protocol/serialization tests; design-safety review. | confirmed |
| FR-7 | Cooperative early stopping procedure contract | FR-6 | Provide a generic public policy/interface and stage-integrated signal that project code can use to stop an active stage or run itself. | Saves run time without making Loom parse downstream metrics or kill executor work directly. | Public contract for cooperative early-stop decisions/signals; no scheduled-trial cancellation; no executor-forced kill in v13 default scope; no new core status enum. | Stage/run code can implement arbitrary early stopping and signal Loom through a stable generic contract. | Runner/sweep layer records `CANCELLED` with `LifecycleReason(code="early_stop")`, exposes early-stop reason in feedback/status, and derives sweep/trial outcome `EARLY_STOPPED` for presentation and adapters. | Contract tests for signal/policy shape, lifecycle reason mapping, runner/sweep handling, and derived outcome rendering. | confirmed |
| FR-8 | Authority-backed coordination records | FR-2 | Record sweep identity and trial references in workspace/sweep coordination whenever an authority-backed runtime is used. | Keeps sequential v13 compatible with future concurrent, queued, and distributed controllers without making manifests the only cross-run index. | Authority-backed runtimes only; simple manifest-only local paths remain available when no authority-backed coordination is configured. | Users still inspect manifests, while authority-aware tooling can see sweep/trial references. | Sweep runner creates/updates `SweepIdentity` and `TrialReference` records with run URIs, trial states, and plain metadata through public coordination APIs. | Contract/integration tests with fake or SQLite coordination store. | confirmed |
| FR-9 | Trial dispatch adapters | FR-2 | Dispatch planned trial run intents through either direct sequential `PipelineRunner` execution or queue-backed whole-run enqueue when queue service/config is provided. | Keeps local sweeps simple while letting authority/queue deployments coordinate trial execution through the existing whole-run queue path. | Direct sequential dispatch and queue-backed dispatch; no SLURM per-trial submission logic in sweep layer beyond queue/delegated adapters already owned elsewhere. | Users can run simple sweeps locally or submit trials through queue configuration without changing trial identity or manifests. | Dispatch adapters consume `TrialSpec`/run URI mappings and either call `PipelineRunner` one trial at a time or create queue enqueue requests for finite planned trials; future incremental providers enqueue proposals as produced. | Unit/integration tests for direct dispatch and queue-backed enqueue shape with fake queue service. | confirmed |
| FR-10 | Sweep status outcome aggregation | FR-3 | Aggregate trial outcomes with separate counts for succeeded, failed, cancelled, early-stopped, running, pending, and related states. | Users need clear sweep progress, especially when early stopping maps to `CANCELLED` internally. | Status aggregation and CLI/API result models. | `loom sweep status` shows early-stopped trials separately from generic cancellation. | Derive `early_stopped` from run/stage lifecycle reason `early_stop`, while preserving raw status and reason details. | Status aggregation tests for normal, failed, cancelled, and early-stopped synthetic trials. | confirmed |

## Behavior Baseline

Included functionality:

- Confirmed: grid and manual deterministic trial planning.
- Confirmed: default generated-trial guard of `100`, with explicit override
  required for larger generated sweeps.
- Confirmed: a generic sweep adapter/provider interface designed before the built-in
  adapters, with deterministic grid and manual sweeps implemented through that
  first-party adapter shape.
- Confirmed: adapter/provider interface supports both finite planned sets and
  future incremental/adaptive proposal streams; finite count/materialization is
  optional.
- Confirmed: manifests and plan-only inspection.
- Confirmed: sequential trial execution through ordinary `RunRequest` values.
- Confirmed: basic sweep status aggregation.
- Confirmed: basic generic collection of trial facts, override values, run status,
  and artifact refs/metadata.
- Confirmed: artifact extraction interface with explicit unsupported/not-implemented
  behavior, but no default metric/payload parsing.
- Confirmed: authority-backed runtimes record sweep/trial coordination facts
  automatically.
- Confirmed: trial dispatch adapter boundary with direct sequential and
  queue-backed dispatch modes.
- Confirmed: CLI commands over public Python APIs.
- Confirmed: adaptive feedback protocol shape sufficient for future Optuna-like
  integrations, with concrete external provider implementations deferred.
- Confirmed: cooperative early-stopping procedure contract so active stage/run code
  can stop itself through a stable generic signal.
- Confirmed: cooperative early-stop maps to existing `CANCELLED` lifecycle state
  with structured `early_stop` reason rather than adding a new core status.
- Confirmed: no cancellation of already scheduled trials in v13.

User-visible behavior:

- Confirmed: users author a sweep spec that references a base config, axes or
  manual trials, and run root.
- Confirmed: users can inspect exact generated trial IDs and overrides before
  running.
- Confirmed: users see stable sweep-local trial IDs and concrete run URIs as
  related but distinct fields.
- Confirmed: users can run the sweep and inspect each trial as a normal run.
- Confirmed: users can queue finite planned trials when queue dispatch is selected,
  then inspect progress with sweep status rather than relying on the sweep
  command to operate as a queue controller.
- Confirmed: users can see a sweep-level status summary and collect selected
  artifact/metadata summaries.
- Confirmed: users can explicitly resume compatible existing sweep manifests; rich
  filtering and retry policies are not part of v13.

Default behavior:

- Confirmed: preserve authored axis and trial order.
- Confirmed: use stable path-safe trial IDs.
- Confirmed: keep `trial_id` separate from `run_uri`; derive/associate run URIs
  through run-root policy and persist the mapping.
- Confirmed: generated adapters stop at `100` trials by default unless explicitly
  overridden.
- Confirmed: continue after failed trial while returning an overall failed sweep
  result if any required trial failed.
- Confirmed: fail rather than overwrite incompatible existing manifests.
- Confirmed: early stopping is cooperative and opt-in by stage/run code.
- Confirmed: manifests are always written; coordination records are additionally
  written whenever the runtime is authority-backed.
- Confirmed: no-queue local use dispatches directly and sequentially; queue
  configuration/service dispatches trial run intents through queue-backed
  whole-run enqueue.
- Confirmed: queue-backed dispatch enqueues finite planned trials and exits or
  returns submission results; ongoing scheduling remains queue-owned.
- Confirmed: sweep status has separate derived counts for early-stopped trials.

Failure behavior and diagnostics:

- Confirmed: spec parse/validation and manifest incompatibility are errors.
- Confirmed: trial execution failures are recorded per trial and reflected in the
  sweep result.
- Confirmed: cooperative early-stopped trials are recorded distinctly from
  infrastructure failures by using `CANCELLED` plus `early_stop` reason and a
  derived sweep/trial outcome.
- Confirmed: collection/status failures should identify sweep dir, trial id,
  artifact id, and underlying run-store/catalog issue.

Explicit deferrals:

- Confirmed: concrete Optuna adapter.
- Confirmed: Bayesian optimization and concrete external adaptive providers.
- Confirmed: bounded local concurrency, SLURM per-trial submission,
  and controller daemon behavior.
- Confirmed: cancelling already scheduled trials.
- Confirmed: executor-forced active-stage termination as the default v13
  early-stopping mechanism.
- Confirmed: domain metric parsing or project-code importing collection behavior.
- Confirmed: failed-only reruns, from-trial selection, rich trial filtering, and
  retry policy.
- Confirmed: implemented artifact payload/metric extraction adapters.

Out-of-scope behavior:

- Confirmed: replacing config merge, scheduler submission, run-store truth, run
  catalog truth, artifact codecs, or queue policy.
- Confirmed: adding new generic `STOPPED` or `EARLY_STOPPED` core lifecycle status
  values.

Context compaction/reset checkpoint:

- Checkpoint status: recorded; design pass should reload this artifact before
  asking design questions.
- Notes path: `docs/roadmap/stage-13/planning.md`
- Resume instruction: reload this planning artifact and
  `.codex/workflows/roadmap-stage-planning.md`, then start the design-agreement
  review using `.codex/prompts/roadmap-stage-design-agreement.md`. Treat the
  confirmed functionality and behavior baseline as binding unless the user
  explicitly reopens it.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Design agreement confirmed. The shape below maps the confirmed behavior
baseline onto source-tree boundaries, public contracts, extension points, and
durable records. Public protocol names remain illustrative for implementation
planning, but the interface shape is confirmed.

Likely modules or packages:

- `src/loom/pipeline/sweep/spec.py`
- `src/loom/pipeline/sweep/trials.py`
- `src/loom/pipeline/sweep/grid.py`
- `src/loom/pipeline/sweep/manual.py`
- `src/loom/pipeline/sweep/manifest.py`
- `src/loom/pipeline/sweep/runner.py`
- `src/loom/pipeline/sweep/status.py`
- `src/loom/pipeline/sweep/collection.py`
- `src/loom/pipeline/sweep/extraction.py`, if the artifact extraction
  interface is separated from collection
- `src/loom/pipeline/sweep/coordination.py`, if coordination-record projection
  is separated from runner orchestration
- `src/loom/pipeline/sweep/dispatch.py`, if trial dispatch adapters are
  separated from runner orchestration
- `src/loom/pipeline/sweep/adapters.py` or `providers.py`, because the provider
  boundary is locked as a first-class v13 design concern
- `src/loom/pipeline/sweep/feedback.py`, if adaptive feedback protocol models
  are kept separate from expansion adapters
- `src/loom/pipeline/sweep/early_stopping.py`, because cooperative
  early-stopping policy/signal contracts are in v13 scope
- `src/loom/cli/sweep.py`

Likely public classes, functions, or protocols:

- `SweepSpec`
- `ManualTrialSpec`
- `TrialSpec`
- `SweepPlan`
- `SweepRunResult`
- `TrialResult`
- `SweepStatus`
- `SweepCollection`
- `ArtifactExtractionAdapter`, `ArtifactExtractionRequest`,
  `ArtifactExtractionResult`, or equivalent extraction interface/result models
  that can report unsupported behavior.
- Coordination projection helpers for `SweepIdentity`, `TrialReference`, and
  trial state mapping, likely internal unless a public helper is useful.
- `TrialDispatchAdapter`, `DirectSequentialDispatchAdapter`,
  `QueueTrialDispatchAdapter`, or equivalent dispatch interface and first-party
  adapters.
- `SweepRunner`
- `SweepAdapter`, `TrialProvider`, or equivalent protocol that returns trial
  proposals/specs for a given sweep context.
- Optional finite-planning protocol or capability, such as
  `FiniteTrialProvider`, `TrialCountEstimate`, or equivalent, for providers
  that can expose a count/materialized plan.
- A provider/proposal iterator or stream type that does not require every
  adapter to implement `__len__`.
- First-party `GridSweepAdapter` and `ManualSweepAdapter` implementations.
- `TrialFeedback`, `TrialObservation`, `SweepFeedbackAdapter`, or equivalent
  adaptive feedback protocol for future optimizers.
- `EarlyStoppingPolicy`, `EarlyStoppingDecision`, `EarlyStop`, or equivalent
  public cooperative early-stop contract for project stage/run code.
- `EARLY_STOPPED` as a sweep/trial outcome or presentation value, derived from
  `CANCELLED` lifecycle records with `LifecycleReason(code="early_stop")`.

Likely internal helpers:

- Grid cartesian product helpers.
- Manual trial validation helpers.
- Trial ID/name/path normalization helpers.
- Trial-to-run-URI mapping helpers.
- Trial count guard helpers.
- Override formatting helpers that lean on config override syntax.
- Manifest read/write and compatibility checks.
- Status/collection read-model helpers.
- Unsupported artifact-extraction result helpers.
- Coordination-record creation/update helpers for authority-backed runtimes.
- Queue enqueue request projection helpers for planned trial run intents.

Data flow:

- Load trusted sweep spec.
- Ask the adapter/provider for trial proposals. Built-in grid/manual adapters
  provide finite materialized plans; future adaptive providers may stream
  proposals without exposing a length.
- Enforce max-trials guard for generated finite plans and for consumed proposal
  streams.
- Write/copy authored spec and generated manifests.
- If authority-backed runtime coordination is available, create/update sweep and
  trial coordination records.
- For each selected trial, build a normal `RunRequest` with combined base,
  overlay, base override, trial override, runtime options, and sweep metadata.
- Dispatch each trial through the selected dispatch adapter: direct sequential
  dispatch calls `PipelineRunner`, queue dispatch submits whole-run queue
  intents for finite planned trials.
- Read run-state/catalog-compatible summaries for status and collection.
- Return structured unsupported/not-implemented results for artifact extraction
  requests until a concrete extraction adapter exists.

Dependency direction:

- `loom.pipeline.sweep` may depend on public config, pipeline planning/runtime,
  execution request/result models, stores/read models, serialization,
  fingerprints/provenance value helpers, and run catalog models when needed.
- `loom.pipeline.sweep` must not import CLI, project packages, optional
  optimizer libraries, concrete queue adapters as mandatory dependencies, or
  SLURM wrappers directly.
- `loom.cli.sweep` calls public sweep APIs and formats output.

Extension points and flexibility boundaries:

- Confirmed: built-in grid/manual expansion should be one implementation of a
  generic trial-generation concept.
- Confirmed: the generic base interface should not assume every provider is sized.
  Finite providers can expose count/materialization capabilities; incremental
  providers can expose proposal streams and feedback hooks.
- Confirmed: external optimizers can initially generate manual trial lists or call
  Python planning APIs. Later adapters can implement trial provider/feedback
  protocols if planning locks them.
- Confirmed: queue or SLURM submission should be a trial-run dispatch adapter later,
  not part of expansion semantics.
- Confirmed: artifact extraction is its own adapter seam later; v13 collection stays
  metadata-first and reports unsupported extraction explicitly.
- Confirmed: coordination records are a runtime/store integration seam, not the
  authoritative source for per-run lifecycle; run-store/authority remains run
  lifecycle truth.
- Confirmed: dispatch is separate from trial generation. Queue-backed dispatch
  consumes planned trial run intents and should not change expansion semantics
  or implement scheduler-specific behavior directly.

Generic interface, adapter, or protocol shape:

- Confirmed direction: design the generic adapter/interface first, then build
  Loom's deterministic grid and manual sweep behavior as first-party adapters.
- Confirmed direction: define an adaptive feedback protocol now, but defer
  concrete Optuna or other optimizer adapters.
- Confirmed direction: prefer a minimal provider surface that emits explicit `TrialSpec`
  values or `TrialProposal` values with plain-data metadata and stable provider
  provenance.
- Confirmed direction: support finite planned sets and future incremental trial
  generation through the same base concept. Add optional finite capabilities
  where useful instead of requiring every provider to support `len()`.
- Confirmed direction: `trial_id` is stable sweep-local identity; `run_uri` is
  the concrete run address/reference and should be bound to `trial_id` in
  manifests and coordination records.
- Confirmed direction: the adapter/provider interface is a stable public v13
  contract.
- Confirmed direction: early stopping is cooperative and stage/run-integrated.
  Loom should provide the generic policy/signal contract and record the
  controlled early-stop outcome without parsing domain metrics or killing
  executor work directly by default.
- Confirmed direction: do not add `EARLY_STOPPED` or generic `STOPPED` to core
  lifecycle statuses. Use `CANCELLED` plus structured reason
  `code="early_stop"` for persisted run/stage lifecycle, and derive
  sweep/trial early-stopped outcome from that reason.
- Confirmed direction: keep adaptive feedback and cooperative early-stopping contracts
  separate from deterministic expansion so default v13 trial generation remains
  deterministic while future adaptive providers have a stable integration point.

Future-roadmap impact:

- V14 can discover provider/adaptor implementations explicitly through plugins.
- Later adaptive/provider stages can add result feedback, early stopping, and
  external trial IDs without changing core grid/manual manifests if provider
  metadata slots are planned now.
- Queue/distributed work can use trial references, leases, and queue intents
  without changing ordinary trial run semantics.

Compatibility constraints:

- Avoid hard optional optimizer dependencies.
- Avoid provider-specific persisted fields that cannot be represented as
  plain-data metadata.
- Preserve stable manifest versioning and clear unsupported-feature errors.

## Design Agreement Queue

| ID | Design decision | Depends on | Order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DQ-1 | Source-tree and import boundary | FR-1 through FR-10 | 1 | auto-approved candidate | Keep runtime code in `loom.pipeline.sweep`, with a thin `loom.cli.sweep`; no project-package, CLI, optimizer, or scheduler-specific imports in sweep core. | Preserves the documented dependency direction and domain-neutral runtime boundary. | Not needed; `docs/structure.md` and `docs/features/sweeps.md` are explicit. | recorded |
| DQ-2 | Public sweep API publication boundary | DQ-1 | 2 | recorded recommendation | Publish stable sweep types from `loom.pipeline.sweep`; avoid top-level `loom.__init__` re-exports in v13 unless a type is foundational and import-cheap. | Keeps the stable contract importable without making all sweep internals part of the package root. | Not needed; matches public API policy. | recorded |
| DQ-3 | Provider/proposal protocol shape | FR-5, FR-6 | 3 | confirmed | Use an explicit contextful provider protocol, not a bare `__iter__` provider: a provider receives planning context and yields `TrialProposal`/`TrialSpec` values; finite planning/count is an optional capability; feedback is a separate optional observer/hook. | This is the core public adapter contract and will affect grid/manual, future Optuna-like adapters, manifests, tests, and plugin discovery. | User agreed to lock the explicit contextful provider protocol. | confirmed |
| DQ-4 | Trial identity ownership | DQ-3 | 4 | recorded recommendation | Loom owns canonical `trial_id`, `trial_index`, `run_uri` binding, and manifest identity; providers may supply external IDs in metadata only. | Prevents external tools from destabilizing run-store/catalog identity while still preserving provider provenance. | Not needed; follows confirmed `trial_id` separate from `run_uri` decision. | recorded |
| DQ-5 | Finite versus incremental capability split | DQ-3 | 5 | recorded recommendation | Base provider supports proposal streams; finite providers expose optional materialization/count/plan-summary capability; the `100` guard applies to generated finite plans and consumed proposal streams. | Lets deterministic grid/manual stay inspectable while future adaptive providers avoid a fake `len()`. | Not needed; this is the direct implementation of the confirmed DQ-3 behavior. | recorded |
| DQ-6 | Built-in grid/manual implementation form | DQ-3, DQ-5 | 6 | auto-approved candidate | Implement grid and manual as first-party providers/adapters that satisfy the same public protocol and have contract tests. | Keeps built-ins from becoming a special one-off path and proves the adapter contract. | Not needed; directly confirmed by the user. | recorded |
| DQ-7 | Trial dispatch boundary | FR-9 | 7 | recorded recommendation | Keep dispatch separate from generation. Dispatch adapters consume planned trial run intents and return dispatch/submission results. | Avoids coupling optimization strategy to execution backend or queue policy. | Not needed; user confirmed queue-backed submission should go through queue/controller authority. | recorded |
| DQ-8 | Queue-backed dispatch semantics | DQ-7 | 8 | recorded recommendation | Queue dispatch enqueues finite planned trials as whole-run queue intents and returns submission results; queue service/controller owns ongoing draining and lifecycle. | Keeps `loom sweep run` from becoming a queue daemon and reuses existing queue ownership. | Not needed; confirmed by the user and existing queue model. | recorded |
| DQ-9 | Manifest and coordination persistence | FR-2, FR-8 | 9 | recorded recommendation | Always write versioned sweep/trial manifests; additionally create/update `SweepIdentity` and `TrialReference` when an authority-backed coordination store is available. | Manifests remain portable, while authority-backed runtimes get durable cross-run facts for future concurrency. | Not needed; user explicitly confirmed authority-backed coordination facts. | recorded |
| DQ-10 | Status and outcome model | FR-3, FR-10 | 10 | recorded recommendation | Sweep status is a read model over manifests plus run/queue/coordination state; `early_stopped` is a derived trial outcome from `CANCELLED` plus `early_stop` reason. | Prevents sweep status from becoming a second lifecycle authority and keeps user output clear. | Not needed; follows confirmed lifecycle mapping. | recorded |
| DQ-11 | Cooperative early-stop public signal shape | FR-7, DQ-10 | 11 | confirmed | Provide `context.stop_early(...)` as the ergonomic stage/run API, implemented by raising a typed `EarlyStop`/`EarlyStopping` signal carrying message and plain-data detail. Runner/executor handling catches that stable signal and records `CANCELLED` plus `LifecycleReason(code="early_stop")`; policy helpers may raise the same signal directly. | This changes the public stage/run contract and affects runner error handling, status records, sweep summaries, and tests. | User selected the context helper backed by the typed signal primitive. | confirmed |
| DQ-12 | Adaptive feedback protocol shape | DQ-3, DQ-10, DQ-11 | 12 | recorded recommendation | Define plain-data `TrialObservation`/feedback records carrying trial outcome, lifecycle reason, artifact refs/metadata, and optional user-supplied observations; do not parse domain metrics or drive adaptive behavior in v13. | Gives future optimizers a neutral feedback channel without making Loom know objective semantics. | Not needed; this follows confirmed domain-neutrality constraints, confirmed DQ-3 provider shape, and confirmed DQ-11 early-stop shape. | recorded |
| DQ-13 | Artifact extraction seam | FR-4 | 13 | recorded recommendation | Keep collection metadata/artifact-ref first. Define an extraction adapter interface whose default behavior is explicit unsupported/not-implemented diagnostics. | Preserves future extraction extensibility without importing codecs/project code or defining metric semantics now. | Not needed; user confirmed this shape. | recorded |
| DQ-14 | CLI/API behavior boundary | FR-1 through FR-4, FR-9, FR-10 | 14 | recorded recommendation | CLI commands call public sweep APIs and expose text/JSON results for plan/run/status/collect; CLI does not own planning, dispatch, or collection semantics. | Keeps behavior testable in Python APIs and CLI-thin like existing commands. | Not needed; repo CLI pattern is clear. | recorded |

## Design Decisions

| ID | Decision | Resolution | Rationale | Alternatives rejected | Revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- |
| DD-1 | Sweep implementation boundary | `loom.pipeline.sweep` owns sweep specs, trial generation, manifests, dispatch orchestration, status aggregation, collection records, and public protocols; `loom.cli.sweep` formats command output. | Matches `docs/structure.md` and `docs/features/sweeps.md`; keeps CLI and project code out of runtime internals. | Top-level sweep package outside pipeline; CLI-owned sweep implementation. | Future source-tree update moves sweep ownership out of pipeline. | recorded |
| DD-2 | Public API exposure | Stable v13 sweep contracts are exported from `loom.pipeline.sweep`, with submodules allowed to move internally behind package exports. | Follows public API policy that stable imports matter more than stable files, while avoiding heavy top-level imports. | Re-exporting all sweep types from `loom.__init__`; requiring users to import only deep internal modules. | Sweep APIs become foundational enough to warrant package-root exports. | recorded |
| DD-3 | Provider contract style | Use an explicit contextful provider protocol with proposal stream, optional finite capabilities, and separate feedback hook. | More extensible than bare iteration because it can carry context, diagnostics, provider metadata, manifest compatibility, and future plugin/provider state. | Bare `__iter__` as the primary public contract; monolithic optimizer object that owns execution. | Design-safety review finds the protocol too broad/narrow, or the first external provider integration exposes missing context. | confirmed |
| DD-4 | Dispatch contract style | Separate trial generation from trial dispatch; dispatch consumes planned run intents. | Keeps grid/manual/adaptive generation independent from direct, queue, and future scheduler dispatch. | Provider owns dispatch; sweep runner calls queue APIs directly from expansion code. | Queue run-intent contract cannot represent needed trial facts. | recorded |
| DD-5 | Persistence authority split | Versioned manifests are always written; authority-backed coordination records are an additional runtime-backed index. | Preserves offline portability and future coordination without making the database the only source of sweep shape. | Coordination-only sweep state; manifest-only state even under authority runtime. | Coordination schema cannot carry required trial metadata. | recorded |
| DD-6 | Early-stop lifecycle mapping | Persist `CANCELLED` plus structured `early_stop` reason; derive `early_stopped` sweep outcome. | Avoids broad lifecycle enum churn while preserving stable user semantics. | Add `STOPPED` or `EARLY_STOPPED` core lifecycle statuses. | Core consumers cannot reliably derive early-stop semantics from reason metadata. | recorded |
| DD-7 | Early-stop signal style | Provide `context.stop_early(...)` as the ergonomic public API, backed by a typed cooperative `EarlyStop`/`EarlyStopping` signal carrying message and plain-data detail. Policy helpers may raise the same typed signal directly. | Fits existing stage execution without broadening the stage return type, gives stage code a readable public API, and gives runner/executor handling one stable primitive to map onto `CANCELLED` plus `early_stop` reason. | Return-value API that broadens `Stage.run()` to return `Mapping[str, ArtifactRef] \| StageOutcome`; executor-forced cancellation by default; scheduled-trial cancellation; metric parser in sweep core. | Design-safety review finds exception handling too invasive, or a future stage-outcome envelope is intentionally introduced. | confirmed |
| DD-8 | Artifact extraction | Define extraction adapter records now, but default extraction requests return unsupported/not-implemented diagnostics. | Gives a stable future seam without adding domain/codecs semantics to v13. | Implement metric/artifact payload extraction now; omit extraction seam entirely. | A generic safe plain-data extraction behavior is selected later. | recorded |

## Design Agreement Triage

Resolved directly from repo evidence and confirmed behavior:

- `loom.pipeline.sweep` is the runtime boundary; `loom.cli.sweep` stays thin.
- Built-in grid/manual behavior should exercise the same adapter/provider seam
  rather than bypass it.
- Trial generation, dispatch, artifact extraction, status aggregation, and
  coordination projection are separate seams.
- Direct sequential and queue-backed dispatch are adapter implementations, not
  sweep strategies.
- Versioned manifests are always written; authority-backed coordination facts
  are recorded whenever the runtime provides that authority.
- Early stopping remains a cancellation reason in core lifecycle records and a
  derived sweep/trial outcome in sweep presentation.

High-impact discussion still required:

- None.

Blocked decisions:

- None.

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| Provider protocol is intentionally public before any external optimizer adapter | DQ-3, DQ-5, DQ-6, DQ-12 | Future Optuna/Ray Tune/plugin providers may need additional provider context or ask/tell lifecycle details | Protocol could be too narrow if it is only tested through grid/manual, or too broad if it tries to model optimizer ownership now | Keep v13 protocol contextful but minimal; require fake finite and unsized provider contract tests, provider metadata/provenance slots, optional finite capability, and structured unsupported diagnostics | recorded recommendation |
| Early-stop helper touches execution core, not only sweep code | DQ-11, DD-7, FR-7, FR-10 | Later reliability retry/timeout/cancellation policies could conflict if early stop is treated as failure or as scheduler cancellation | A stage-return envelope or executor-forced cancellation path would require wider refactors if introduced accidentally in v13 | Implement `context.stop_early(...)` as an ergonomic helper that raises a typed signal; map to `CANCELLED` plus `early_stop`; do not add `StageOutcome`, `STOPPED`, scheduled cancellation, retry, or timeout semantics in v13 | recorded recommendation |
| Queue dispatch and coordination could accidentally become sweep scheduling | DQ-7, DQ-8, DQ-9, FR-8, FR-9 | Later distributed controllers and reliability policies need queue/controller ownership to remain separate | Dispatch adapter could overfit to current local queue implementation or mutate lifecycle outside run/queue authorities | Keep dispatch as planned-trial-run-intent projection; queue adapter enqueues finite plans and returns submission results; status aggregates queue/run/coordination read models without controlling the queue loop | recorded recommendation |
| V12 portable-run exchange is adjacent compatibility, not a sweep export format | FR-2, FR-4, DQ-9, DQ-13 | V12 phases are pending; future bundle/export APIs may land while v13 planning or implementation proceeds | Sweep manifests could duplicate bundle/export semantics or become incompatible with run-catalog/bundle inspection | Preserve ordinary `run_uri`/artifact-ref/run metadata compatibility; do not define sweep-specific bundle/export behavior; recheck landed v12 APIs before implementation phases that touch collection/export compatibility | recorded recommendation |
| Artifact extraction seam is deliberately unsupported in v13 | FR-4, DQ-13 | Later external artifact interfaces and payload materialization may need different extraction/adaptor details | A premature extraction API could imply domain metric parsing or project-code imports | Keep v13 collection metadata/artifact-ref first; extraction interface returns explicit unsupported/not-implemented diagnostics until a later stage selects concrete extraction behavior | recorded recommendation |

Gate result:

- Status: passed
- Reviewer: managing Codex local design-safety review using
  `.codex/prompts/roadmap-stage-design-safety-review.md`. No separate reviewer
  subagent was used in this pass.
- Blockers: none
- Recorded recommendations:
  - Keep provider/proposal protocol contextful, minimal, and contract-tested
    with first-party grid/manual plus fake finite and unsized providers.
  - Keep early stopping as `context.stop_early(...)` over a typed signal mapped
    to `CANCELLED` plus `early_stop`; do not broaden `Stage.run()` return type
    in v13.
  - Keep queue dispatch as enqueue-only for finite planned trials; sweep status
    reads queue/run/coordination state but does not control queue draining.
  - Keep v12 compatibility as ordinary-run compatibility; do not create a
    sweep-specific export or bundle format.
  - Keep artifact extraction unsupported by default with machine-readable
    diagnostics.
- Future-roadmap impact summary:
  - V14 plugin discovery can load sweep providers later because the provider
    protocol is explicit and plugin-free in v13.
  - V15/V16 external artifact work can preserve artifact refs and later attach
    extraction/materialization behavior without v13 parsing payloads.
  - V19 reliability can add retry, timeout, event, and cancellation policies
    without v13 early stop claiming those behaviors.
  - Future distributed or adaptive controllers can reuse trial references,
    dispatch adapters, and feedback records without changing grid/manual
    manifests.
- Generic interface, adapter, and protocol assessment:
  - Passed. Provider/proposal, finite capability, feedback, dispatch,
    extraction, and early-stop seams are generic enough for the documented
    future consumers when kept to plain-data records and explicit unsupported
    behavior.
- Planning revisions required:
  - Phase shaping must place public contract work before built-in provider,
    dispatch, and CLI behavior.
  - Phase shaping must treat early-stop execution lifecycle work as a
    prerequisite for sweep `early_stopped` status rendering.
  - Phase execution must recheck landed v12 APIs before depending on bundle or
    portable-run exchange surfaces.
- Accepted risks:
  - Provider and feedback protocols may need widening when the first concrete
    external optimizer adapter is designed.
  - Early-stop signal handling changes execution lifecycle code and therefore
    needs tight tests across local executor, runner, status, and sweep
    aggregation.
  - Queue dispatch adapter design may need refinement when bounded or
    distributed sweeps are implemented later.
- Revisit triggers:
  - A concrete external provider cannot express required proposal or feedback
    state through plain-data metadata/context.
  - Core lifecycle consumers cannot reliably derive early-stop semantics from
    structured reason metadata.
  - Queue service contracts cannot represent finite trial run intents without
    sweep-specific queue policy.
  - V12 final APIs introduce run/export compatibility requirements not captured
    by ordinary `run_uri` plus artifact-ref collection.

## Practical Design Notes

Public Python API surface:

- Confirmed by design agreement; see proposed implementation shape and
  design-agreement queue.

CLI surface:

- Confirmed: `loom sweep plan`, `loom sweep run`, `loom sweep status`,
  `loom sweep collect`.

Persisted records and file layout:

- Confirmed: copied authored sweep spec, versioned `sweep.json`, versioned
  `trials.json`, optional `trials.csv`, ordinary trial run directories.

Import boundaries and dependencies:

- Confirmed: keep optimizer/provider dependencies outside core; use protocols and
  plugin discovery later.

Failure modes and diagnostics:

- Confirmed: spec validation, expansion, manifest compatibility, trial execution,
  status read, and collection errors should each have sweep-specific context.

Extension points and flexibility boundaries:

- Confirmed: provider/adapters are included as narrow public interfaces;
  concrete adaptive implementations are deferred.

Generic interfaces, adapters, and protocols:

- Confirmed: explicit contextful provider/proposal protocol with optional
  finite capabilities and separate feedback hooks; typed cooperative
  early-stop signal/policy contract; `context.stop_early(...)` is the
  ergonomic API and raises the same typed early-stop signal that policy helpers
  may raise directly.

Future-roadmap compatibility:

- Confirmed: leave room for plugins, external providers, queue dispatch, remote
  stores, reliability/retries, and event sinks.

Maintainability assessment:

- Confirmed: keeping expansion pure and execution delegated should keep the
  first PRs reviewable.

Extensibility assessment:

- Confirmed: provider and dispatch seams are deliberate extension points; keep
  them minimal and contract-tested to avoid both later rewrite and
  Optuna-specific overfitting.

Flexibility and expansion assessment:

- Confirmed: manual trials remain a bridge for external tools even after the
  public provider API exists.

Scalability and future compatibility:

- Confirmed: sequential v13 should still record enough manifest/provider facts
  to support later coordination and concurrency.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No concrete optimizer adapter in v13 | User confirmed concrete Optuna support should be deferred; avoids dependency and provider-specific semantics before the interface stabilizes | A downstream project needs Optuna/Ray Tune/etc. integration after v13 protocols stabilize |
| Adaptive feedback protocol may initially have no concrete external provider | Lets v13 stabilize generic feedback records and adapter contracts without importing optimizer dependencies | The first real external provider adapter is planned or plugin discovery reaches provider loading |
| Cooperative early stopping does not cancel scheduled trials or kill executor work by default | Keeps v13 aligned with ordinary run semantics and avoids scheduler/control complexity; stages can stop themselves through the public signal | Users need queue/scheduler cancellation or executor-enforced stop behavior |
| Early stop maps to `CANCELLED` plus reason rather than a new core status | Avoids broad lifecycle enum churn and treats early stopping as a controlled cancellation reason | Core lifecycle consumers cannot reliably derive early-stop semantics from reason metadata |
| Artifact extraction interface exists before concrete extraction behavior | Gives future collectors a stable adapter seam without importing codecs/project code or defining metric semantics in v13 | A generic safe plain-data extraction behavior is explicitly selected in a later roadmap stage |
| Authority-backed coordination records are automatic when authority runtime is used | Gives future concurrency/distribution and authority-aware tooling a durable sweep/trial index without replacing manifests | Coordination schema or authority capabilities cannot represent required v13 trial metadata |
| Queue-backed dispatch is included when queue config/service is supplied | Keeps sweep trial execution cohesive with whole-run queue/controller infrastructure | Queue service contract proves insufficient for trial run intent submission or would require new queue policy outside v13 scope |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Grid learning-rate/seed sweep | Stable cartesian expansion, IDs, manifests, sequential run | Base config with axes over ordinary overrides | Unit expansion plus CLI plan/run smoke | confirmed |
| Trial-count guard | Generated sweep with more than `100` trials fails unless explicitly overridden | Grid adapter with large axis product | Unit and CLI plan tests | confirmed |
| Manual ablation list | Explicit trial overrides and names | Hand-authored trials | Unit manual expansion plus manifest test | confirmed |
| Failed trial visibility | Continue after failure and summarize failed trial | Synthetic stage failure | Integration test with fake/minimal runner | confirmed |
| External-generated manual trials | Optuna-like external tool writes manual trial list without a core dependency | Generated sweep spec/manual trials | Contract/docs example; no Optuna import | confirmed |
| Adapter-first built-ins | Grid and manual adapters both satisfy the same generic interface | First-party deterministic providers | Contract tests for adapter protocol and built-in adapters | confirmed |
| Incremental-capable provider contract | Provider protocol can represent finite grid/manual plans and unsized proposal streams | Fake finite and unsized providers | Contract tests for optional finite capability and proposal iteration | confirmed |
| Adaptive feedback shape | Trial result/status/artifact feedback can be represented without domain metric semantics | Synthetic trial observations | Contract tests for feedback records/protocol; no concrete Optuna import | confirmed |
| Cooperative early stopping hook | Stage/run code can call `context.stop_early(...)`, producing `CANCELLED` plus `early_stop` reason and derived trial outcome | Synthetic stage that calls the helper; helper raises the typed early-stop signal | Contract and runner/sweep tests for reason mapping and outcome rendering | confirmed |
| Generic artifact-ref collection | Collect artifact refs and override columns | Synthetic runs with artifact metadata | Status/collection tests | confirmed |
| Unsupported extraction request | Artifact extraction interface reports explicit unsupported/not-implemented behavior | Synthetic collection request naming an extractor | Contract test for diagnostic shape | confirmed |
| Authority-backed coordination records | Sweep/trial coordination facts are recorded alongside manifests | Fake or SQLite authority-backed coordination store | Integration tests for `SweepIdentity` and `TrialReference` creation/update | confirmed |
| Queue-backed dispatch | Planned trials are submitted as whole-run queue intents when queue config/service is supplied | Fake queue service/repository | Integration tests for enqueue shape and trial/run mapping | confirmed |
| Queue status aggregation | Sweep status aggregates queued/running/completed trial progress without acting as queue controller | Fake queue and synthetic run states | Integration tests for queue progress readback | confirmed |

## Validation Strategy

Confirmed. Default validation stays local, deterministic, synthetic, and
domain-neutral. No Optuna, remote service, network, real cluster, or downstream
project package is required.

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import boundary | Sweep imports stay below CLI and avoid optional optimizer/project imports | Package tests | package | `tests/package/` plus import-boundary tests | confirmed |
| Spec parsing | Valid/invalid grid/manual specs and plain-data metadata | Unit tests | unit | `tests/unit/loom/pipeline/sweep/` | confirmed |
| Expansion | Stable order, IDs, overrides, count limits | Unit/contract tests | unit/contract | sweep expansion tests | confirmed |
| Manifests | Versioned write/read and compatibility checks | Contract tests | contract | `tests/contracts/` and sweep manifest tests | confirmed |
| Runner delegation | Sequential `RunRequest` construction and failure policy | Unit/integration with fake runner | unit/integration | sweep runner tests | confirmed |
| Status/collection | Aggregation from synthetic runs and artifact summaries | Integration/contract tests | integration/contract | sweep status/collection tests | confirmed |
| CLI | Plan/run/status/collect text and JSON | CLI/e2e tests | integration/e2e | `tests/integration/cli`, `tests/e2e` where practical | confirmed |
| Provider seam | Generic adapter interface, built-in grid/manual adapters, provider metadata, and no dependency on Optuna | Contract/import-boundary tests | contract/package | provider protocol and import-boundary tests | confirmed |
| Provider finite/incremental split | Finite materialization is optional; unsized providers can propose trials without `len()` | Contract tests | contract/unit | fake finite and unsized providers | confirmed |
| Adaptive feedback | Feedback records/protocol carry plain-data observations without domain metrics in core | Contract/serialization tests | contract/unit | feedback record round-trip and adapter hook tests | confirmed |
| Early stopping | `context.stop_early(...)` raises typed signal; no scheduled-trial cancellation; `CANCELLED` plus `early_stop` reason; derived trial outcome | Contract/unit/integration as needed | contract/unit/integration | context helper, executor/runner lifecycle, status aggregation tests | confirmed |
| Artifact extraction seam | Unsupported extraction behavior is explicit and machine-readable | Contract/unit tests | contract/unit | extraction adapter diagnostic tests | confirmed |
| Coordination recording | Authority-backed sweep/trial records are created and updated without replacing run-store truth | Contract/integration tests | contract/integration | fake/in-memory and SQLite coordination store tests | confirmed |
| Dispatch adapters | Direct sequential dispatch calls runner; queue dispatch enqueues planned trial intents | Unit/integration tests | unit/integration | fake runner and fake queue service tests | confirmed |
| Status outcomes | Sweep status distinguishes succeeded, failed, cancelled, early_stopped, running, queued/submitted, and pending outcomes | Unit/integration tests | unit/integration | synthetic run/queue/coordination status tests | confirmed |

## Phase Sketch

Confirmed. The implementation plan should preserve these phase boundaries unless
final v12 API rechecks expose a concrete adjustment need.

| Phase | Proposed slug | Goal | Primary ownership | Key acceptance criteria | Validation obligations | Design notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `sweep-contracts-manifests` | Establish sweep package contracts, provider/proposal protocols, feedback records, extraction diagnostics, trial/sweep value models, and versioned manifest schemas without execution or CLI behavior | `loom.pipeline.sweep` models/protocols/manifests | Public contracts round-trip as plain data; provider protocol supports contextful proposal streams and optional finite capability; manifest compatibility errors are structured; extraction default is explicit unsupported | Package, unit, contract | This is the public contract foundation. Keep optimizer dependencies and plugin discovery out of core. |
| 2 | `grid-manual-planning` | Implement first-party grid and manual providers, deterministic expansion, stable trial IDs/order, default `100` generated-trial guard, run URI mapping, and plan-only APIs | `loom.pipeline.sweep` spec/grid/manual/trials/planning | Same spec expands deterministically; manual and grid use the provider protocol; large generated plans fail without explicit override; authored spec/manifests can be written/read | Unit, contract, CLI smoke where useful | Built-ins must prove the provider seam rather than bypass it. |
| 3 | `early-stop-direct-dispatch` | Add `context.stop_early(...)` over typed early-stop signal, execution lifecycle mapping to `CANCELLED` plus `early_stop`, direct sequential dispatch, per-trial `RunRequest` construction, failure policy, and compatible resume behavior | `loom.pipeline.context`, execution lifecycle, `loom.pipeline.sweep.runner/dispatch` | Early-stop helper produces structured cancellation reason; direct dispatch runs remaining trials after failure; trial run metadata carries sweep/trial facts; explicit compatible resume rejects incompatible manifests | Unit, contract, integration | Early-stop lifecycle support must land before status renders derived `early_stopped`. Do not broaden `Stage.run()` return type. |
| 4 | `coordination-queue-status` | Record authority-backed sweep/trial coordination facts, implement queue-backed finite trial dispatch, and aggregate status from manifests plus run/queue/coordination read models | `loom.pipeline.sweep.coordination/dispatch/status`, `loom.queue` integration seams | Authority-backed runtimes create/update `SweepIdentity` and `TrialReference`; queue dispatch enqueues finite planned trial intents and exits; status reports pending/running/queued/succeeded/failed/cancelled/early_stopped without controlling queue draining | Contract, integration | Dispatch remains separate from generation; queue service/controller owns ongoing scheduling. |
| 5 | `sweep-collection-cli-hardening` | Implement metadata/artifact-ref collection, unsupported extraction diagnostics, `loom sweep plan/run/status/collect` text and JSON surfaces, docs, and final hardening | `loom.pipeline.sweep.collection`, `loom.cli.sweep`, docs/tests | Collection reports trial facts and artifact refs without loading payloads or parsing metrics; CLI remains thin; final validation covers examples and import boundaries | Package, unit, contract, integration, limited e2e | Recheck landed v12 bundle/export APIs before documenting compatibility; do not create sweep-specific export/bundle behavior. |

Phase-shaping guardrails:

- Public contracts and persisted schemas land before behavior that depends on
  them.
- Execution lifecycle changes for early stop land before sweep status derives
  `early_stopped`.
- Queue-backed dispatch is not a queue controller and must not own draining,
  cancellation of scheduled trials, or queue policy.
- V13 implementation should target current `develop`, but each phase execution
  plan must recompute stack predecessor and target branch according to the
  repository stacked-phase workflow.
- If v12 phases land before v13 implementation phases, recheck `loom.runs`
  bundle/export/import APIs and keep v13 compatible with ordinary-run
  inspection/export rather than introducing sweep-specific export behavior.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | FRQ-1 through FRQ-16 and FR-1 through FR-10 trace to v13 roadmap, `sweeps.md`, adjacent queue/coordination work, and confirmed user answers | pass | None |
| Requirement-to-design traceability | Design-agreement queue resolved; repo-supported boundaries recorded; DQ-3 provider protocol and DQ-11 early-stop signal/helper shape confirmed | pass | None |
| Design-safety review completed | Local design-safety review passed with no blockers; recommendations recorded in this artifact | pass | None |
| Future-roadmap impact considered | Design-safety review covers v14 providers/plugins, v15/v16 external/remote artifacts, v19 reliability/event sinks, queue/distributed sweeps, and v12 portable-run exchange compatibility | pass | None |
| Generic interface, adapter, and protocol flexibility considered | Generic provider/proposal, dispatch, feedback, extraction, and early-stop seams are drafted, design-agreement confirmed, and design-safety reviewed | pass | None |
| Example-to-validation traceability | Examples and validation matrix confirmed with package, unit, contract, integration, CLI/e2e, and no-default-external-service obligations | pass | None |
| Phase-shaping readiness | Five-phase sketch confirmed with phase boundaries, acceptance criteria, validation obligations, design notes, and v12 recheck guardrail | pass | None |
| Unresolved blocked or needs-discussion functionality or design decisions | No unresolved functionality-agreement or design-agreement questions remain | pass | None |
| V12-facing assumption recheck | V12 planning is confirmed and `docs/roadmap/stage-12/implementation-plan.md` passed its plan quality gate; v12 phases are pending, so v13 must recheck landed APIs during phase execution | pass | Carry recheck guardrail into implementation plan and phases |

Readiness result:

- Status: confirmed; implementation-plan drafting may proceed
- Implementation-plan drafting blockers:
  - None.
- Accepted risks:
  - Provider and feedback protocols may need widening after the first concrete
    external optimizer adapter.
  - Early-stop signal handling touches execution lifecycle and needs focused
    contract/integration coverage.
  - Queue-backed dispatch may need future refinement for bounded or
    distributed sweeps.
- Assumptions to carry forward:
  - See handoff assumptions below.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Should v13 optimize first for deterministic built-in grid/manual sweeps, with adapter hooks for future providers, or should a public provider protocol be a first-class v13 deliverable? | Scope, APIs, phases, validation | Design interface first; implement grid/manual as first-party adapters | answered |
| Should concrete Optuna support be explicitly deferred, or should v13 include a proof-of-shape adapter behind an optional dependency? | Dependency policy, plugin roadmap, adaptive behavior | Defer concrete Optuna; focus on robust future adapter integration | answered |
| Should adaptive trial generation/result feedback be entirely deferred, or should v13 define a dormant feedback protocol for future optimizers? | Interface design, manifests, status/result model | Define adaptive feedback protocol now; concrete optimizer behavior deferred | answered |
| Should early stopping in v13 be interface-only, or should v13 ship minimal built-in early stopping behavior? | Public API, result collection, execution control, failure semantics, validation | Cooperative policy/interface and stage-integrated signal; no scheduled-trial cancellation | answered |
| How should cooperative early stop map onto run/stage status and sweep trial outcome? | Run-store compatibility, catalog/status output, resume behavior, CLI exit code | `CANCELLED` lifecycle state plus structured `LifecycleReason(code="early_stop")`; derived sweep/trial outcome `EARLY_STOPPED` | answered |
| What should the default failure policy be for sequential sweeps? | Run behavior, CLI exit code, status semantics | Continue on failure, run remaining trials, return failed sweep result if any required trial failed | answered |
| How much sweep resume/filtering belongs in v13? | CLI/API behavior, manifest compatibility, phase scope | Fail on incompatible manifests; explicit compatible resume through normal run resume; defer rich filtering/rerun | answered |
| Should collection read plain-data artifact payloads in v13, or only collect artifact refs/metadata? | Domain neutrality, codecs, optional imports, CLI output | Artifact refs and metadata only; define extraction interface with explicit unsupported behavior | answered |
| Should sequential v13 record workspace coordination `SweepIdentity`/`TrialReference` facts by default, or only manifests? | Store coupling, future concurrency, status | Always record coordination facts when an authority-backed runtime is used; always write manifests | answered |
| What default guard should generated sweeps use? | Accidental large runs, CLI/API defaults, validation | Default max generated trials is `100`, explicit override required for larger generated sweeps | answered |
| Should stable trial IDs link to `run_uri` or stay separate? | Manifests, coordination, run catalog identity, path stability | Keep `trial_id` sweep-local and separate from `run_uri`; persist mapping in manifests/coordination records | answered |
| Should the provider interface assume finite planned trial sets or support incremental generation? | Adapter API, future optimizers, finite planning, validation | Base proposal stream supports finite and incremental providers; finite count/materialization is optional | answered |
| Should queue-backed trial submission be represented as a future dispatch adapter now, or omitted until a later phase? | Queue integration, provider/dispatch separation | Include queue-backed dispatch adapter when queue config/service is supplied; keep direct sequential dispatch for no-queue local use | answered |
| What primary workflow should v13 optimize for? | UX, validation, phase boundaries, future adaptive design | Finite plan/inspect/run-or-queue workflow with predictable artifacts and status | answered |
| Should queue-backed sweep execution act as a long-running queue controller? | Queue ownership, service lifecycle, CLI behavior | No; enqueue finite planned trials and aggregate status through `loom sweep status` | answered |
| How should early-stopped trials appear in sweep summaries? | CLI/API status output, adapter feedback, user clarity | Separate derived `early_stopped` count/outcome from generic cancelled | answered |
| Should the public provider/proposal adapter be an explicit contextful protocol rather than a bare iterator? | Public API stability, external providers, plugin discovery, finite/incremental support, feedback | Use explicit contextful provider protocol with proposal stream, optional finite planning/count capability, and separate feedback hook | answered |
| Should cooperative early stopping use a typed exception/signal, a return-value decision API, or a context method? | Public stage/run contract, runner integration, lifecycle reason mapping, tests | Use `context.stop_early(...)` as the ergonomic API backed by a typed `EarlyStop`/`EarlyStopping` signal carrying plain-data reason detail; helper policies may raise the same signal directly | answered |

## Handoff Notes

Implementation-plan draft inputs:

- Use this planning artifact as the primary source after final planning
  confirmation.
- Draft the implementation plan around the confirmed five-phase sketch:
  contracts/manifests; grid/manual planning; early-stop/direct dispatch;
  coordination/queue/status; collection/CLI hardening.
- Carry design-safety recommendations into plan principles, conflicts,
  technical debt, validation, and phase acceptance criteria.
- Record that v12 planning and implementation-plan quality gate are complete,
  while v12 phase APIs may still be pending and must be rechecked before v13
  phase execution depends on them.

Design-safety review result:

- Passed with no blockers. Recommendations and accepted risks are recorded in
  the Design Safety Review section.

Validation and phase-shaping inputs:

- Examples and validation strategy are confirmed.
- Phase sketch is confirmed and ready to be transformed into implementation
  plan phases after final planning confirmation.

Plan-quality-gate risks:

- Provider/adapter abstraction may be either too narrow for Optuna-like future
  tools or too broad for deterministic v13; contract tests with fake finite
  and unsized providers are required.
- Provider interface must avoid assuming every adapter can expose a finite
  count while still keeping v13 deterministic planning inspectable for
  grid/manual.
- Queue dispatch adapter must not collapse sweep expansion, queue policy, and
  scheduler behavior into one layer.
- Sweep status must aggregate queue/run/coordination progress without becoming
  a second queue controller.
- Early-stop semantics depend on structured reason propagation; implementation
  must ensure catalog/status/sweep outputs do not collapse early stop into an
  ambiguous generic cancellation.
- V12 APIs may evolve while v13 implementation is planned; phase execution must
  recheck landed bundle/export surfaces and keep sweeps ordinary-run
  compatible.
- Manifest compatibility and failure policy need precise tests.
- Trial count guard defaults and override behavior need precise CLI/API tests.
- Artifact extraction interface must not imply that v13 can parse metrics or
  import project codecs.
- Coordination records must remain cross-run references and must not become
  duplicate per-run lifecycle truth.

Assumptions to carry forward:

- Grid and manual sweeps are first-party adapters over a generic sweep
  adapter/provider interface.
- Concrete Optuna support is deferred.
- Adaptive feedback protocol is in scope for v13 design.
- Early stopping is cooperative and stage/run-integrated, not scheduler
  cancellation or executor-forced termination by default.
- The sweep adapter/provider interface is a stable public v13 contract.
- Early stop maps to `CANCELLED` lifecycle status plus structured
  `LifecycleReason(code="early_stop")`; sweep/trial output may render
  `EARLY_STOPPED` as a derived semantic outcome.
- Sequential sweep failure policy runs remaining trials and returns an overall
  failed sweep result if any required trial failed.
- V13 supports explicit resume for compatible sweep manifests and defers richer
  rerun/filtering/retry behavior.
- V13 collection is metadata/artifact-ref first and includes only a future
  artifact-extraction adapter seam with explicit unsupported/not-implemented
  behavior.
- V13 records sweep/trial coordination facts whenever an authority-backed
  runtime is used, while manifests remain the durable sweep artifacts.
- V13 includes direct sequential and queue-backed trial dispatch adapters. Queue
  dispatch is used when queue config/service is supplied; direct sequential
  dispatch remains available for no-queue local use.
- Queue-backed dispatch enqueues finite planned trials and leaves ongoing queue
  control to the queue service/controller; sweep status aggregates progress.
- Sweep summaries expose early-stopped trials as a separate derived outcome.
- Generated sweeps use default max-trials guard `100` unless explicitly
  overridden.
- `trial_id` is stable sweep-local identity and remains separate from `run_uri`;
  manifests and coordination records persist their mapping.
- Provider interface should support both finite planned sets and future
  incremental proposal streams, with optional finite/count capabilities rather
  than a mandatory `len()`.
