# Implementation Plan v13: Deterministic Sweeps

## Metadata

- Status: plan quality gate passed; ready for Phase 1 execution planning
- Roadmap stage: `v13`
- Source planning notes:
  `docs/roadmap/stage-13/planning.md`
- Workflow: `.codex/workflows/roadmap-stage-implementation.md`
- Related implementation plans:
  - `docs/roadmap/stage-12/implementation-plan.md`
  - `docs/roadmap/stage-11/implementation-plan.md`
  - `docs/roadmap/stage-10/implementation-plan.md`
  - `docs/roadmap.md`
- Related source docs:
  - `docs/structure.md`
  - `docs/features/sweeps.md`
  - `docs/features/config.md`
  - `docs/features/pipeline.md`
  - `docs/features/execution.md`
  - `docs/features/run-store.md`
  - `docs/features/run-catalog.md`
  - `docs/features/artifacts.md`
  - `docs/features/provenance.md`
  - `docs/features/queue.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/features/plugins.md`
  - `docs/features/remote-stores.md`
  - `docs/features/reliability.md`
- Draft pass: complete on 2026-05-14 from confirmed Stage 13 planning notes
- Refine pass: complete on 2026-05-14 after local plan-quality review
- Plan quality gate: passed on 2026-05-14 after local
  review/refinement/confirmation
- User phase approval: approved on 2026-05-14 for Phase 1 execution planning
  and the five-phase shape below.
- Current phase: Phase 2 - `grid-manual-planning`
- Blockers:
  - No roadmap-stage planning blocker remains.
  - No plan-quality blocker remains; Phase 1 execution planning may begin.

## Summary

- Goal: implement deterministic grid and manual sweeps as collections of
  ordinary Loom runs, with stable manifests, public provider/adapter contracts,
  cooperative early stopping, direct and queue-backed dispatch, status
  aggregation, generic collection, and `loom sweep` CLI commands.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-13/planning.md`.
- Approved behavior: finite plan/inspect/run-or-queue workflow; stable
  sweep-local `trial_id`; default generated-trial guard of `100`; ordinary
  `run_uri` mapping; metadata/artifact-ref collection; run remaining trials
  after failures; explicit compatible resume; authority-backed coordination
  facts when available.
- Source behavior confirmation: complete in the planning artifact.
- Key design constraints: domain-neutral, dependency-light, no concrete Optuna
  or optimizer dependency, no sweep-owned config merge, no scheduler policy in
  sweep core, no project-code metric parsing, no new core `STOPPED` or
  `EARLY_STOPPED` lifecycle state.
- Source design-agreement gate: confirmed with DQ-1 through DQ-14.
- Future-roadmap impact: v14 plugin discovery, v15/v16 external artifact and
  payload materialization, v19 reliability policies and event sinks, future
  adaptive providers, future distributed sweep controllers, and v12
  bundle/export compatibility must be able to build on v13 without inheriting
  grid/manual-only assumptions.
- Reusable interface, adapter, or protocol assumptions: provider/proposal,
  optional finite capability, feedback, dispatch, extraction, and early-stop
  seams are public v13 contracts or contract-shaped unsupported seams.
- Examples covered: grid planning, trial guard, manual ablations, failed-trial
  visibility, external-generated manual trials, adapter-first built-ins, fake
  finite and unsized providers, feedback records, cooperative early stopping,
  metadata/artifact-ref collection, unsupported extraction, coordination
  records, queue dispatch, and queue status aggregation.
- Source phase shaping: five phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-14 after local
  review/refinement/confirmation.
- Out of scope: concrete Optuna or other optimizer adapters, Bayesian
  optimization, default adaptive generation, scheduled-trial cancellation,
  executor-forced early stopping, SLURM per-trial submission, bounded local
  concurrency, distributed controllers, rich rerun/filtering/retry policy, and
  implemented metric or artifact-payload extraction.

## Goal

Implement v13 as Loom's first sweep layer: a deterministic, inspectable
orchestration surface that expands grid/manual trial definitions into stable
ordinary runs while establishing the public contracts needed for future sweep
providers and optimizer integrations.

When complete, users can plan a sweep, inspect exact trial IDs and overrides,
run the planned trials locally or enqueue them through the queue service, see
aggregate status including early-stopped trials, and collect generic trial facts
plus artifact references without Loom parsing project metrics.

## Context

The repository already has the foundations v13 should build on:

- `loom.config` owns override parsing and config composition. Sweeps should
  produce ordinary override inputs and not implement a second merge language.
- `PipelineRunner` and `RunRequest` execute one ordinary run. Sweep execution
  should construct one `RunRequest` per trial and delegate execution.
- `StageContext` is passed to project stage code; it is the correct ergonomic
  place for `context.stop_early(...)`, backed by a typed early-stop signal.
- `RunStatus`, `StageStatus`, and structured lifecycle reasons already support
  `CANCELLED` with reason metadata; v13 should derive `early_stopped` at the
  sweep/status presentation layer rather than add a core status.
- `WorkspaceCoordinationStore` already defines `SweepIdentity`,
  `TrialReference`, and `TrialState` for cross-run sweep facts.
- `loom.queue` already owns whole-run queue items, launch contracts, queue
  service/controller behavior, and cancellation/status ownership. Queue-backed
  sweep dispatch should submit finite trial run intents and return submission
  results, not drain the queue.
- `loom.runs` and run-catalog read models provide metadata-only summaries and
  artifact refs. Sweep status/collection should consume these or equivalent
  store read models instead of copying run lifecycle truth.
- Stage 12 has a confirmed implementation plan for portable run exchange,
  bundles, and exporters. Its phase APIs may still be pending, so v13
  implementation phases must recheck the current code before depending on
  landed v12 surfaces.

## Planning Readiness

- Source planning notes:
  `docs/roadmap/stage-13/planning.md`
- Functionality and behavior baseline:
  complete; the notes lock deterministic planning, manifests, provider
  interface, feedback protocol, early-stop helper/signal, dispatch adapters,
  coordination recording, status outcomes, collection, and deferrals.
- Design-safety review:
  passed with no blockers. The review added phase obligations to keep the
  provider protocol minimal and contract-tested, land early-stop execution
  lifecycle support before status rendering, keep queue dispatch enqueue-only,
  preserve ordinary-run compatibility with v12, and keep extraction unsupported
  by default.
- Examples and validation strategy:
  complete; default validation is local, deterministic, domain-neutral, and
  uses synthetic runs, fake providers, fake queue services, and fake or SQLite
  coordination stores. No Optuna, network, remote service, real cluster, or
  downstream package is required.
- Phase shaping:
  complete; five implementation phases are recorded below.
- Implementation readiness blockers from planning:
  none after final planning confirmation on 2026-05-14.
- Accepted risks and revisit triggers:
  provider and feedback protocols may need widening when a real external
  optimizer adapter is designed; early-stop signal handling touches execution
  lifecycle and needs focused tests; queue dispatch may need future refinement
  for bounded or distributed sweeps.

## Desired Outcome

When all phases are complete:

- `loom.pipeline.sweep` exists as the owning package for sweep specs, trial
  models, provider/proposal protocols, feedback records, manifests, dispatch,
  status, collection, extraction diagnostics, coordination projection, and
  sweep runner orchestration.
- Grid and manual sweep behavior is implemented as first-party providers over
  the same public provider/proposal protocol that future adapters can use.
- Provider/proposal records carry plain-data provider metadata and provenance,
  while Loom owns canonical `trial_id`, `trial_index`, manifest identity, and
  concrete `run_uri` mapping.
- Finite providers expose optional count/materialization capabilities; the base
  proposal stream does not require `__len__`.
- Sweep/trial manifests are versioned plain data and preserve stable trial
  order, IDs, overrides, run URI mappings, provider facts, and compatibility
  metadata.
- `context.stop_early(...)` exists as the ergonomic cooperative early-stop API
  and raises a typed signal that runner/executor handling maps to `CANCELLED`
  plus `LifecycleReason(code="early_stop")`.
- Sweep status derives `early_stopped` from lifecycle reason metadata while
  preserving raw run/stage status and reason details.
- Direct sequential dispatch executes finite planned trials through
  `PipelineRunner`, runs remaining trials after failures, and reports a failed
  sweep result if any required trial failed.
- Queue-backed dispatch enqueues finite planned trial run intents through the
  existing queue service/config path and returns submission results without
  becoming a queue controller.
- Authority-backed runtimes always record sweep/trial coordination facts via
  `SweepIdentity` and `TrialReference` alongside manifests.
- Collection reports trial facts, override values, statuses, and artifact refs
  or metadata. Extraction requests return explicit unsupported/not-implemented
  diagnostics until a later stage implements concrete extractors.
- `loom sweep plan`, `loom sweep run`, `loom sweep status`, and
  `loom sweep collect` expose thin text/JSON CLI wrappers over public Python
  APIs.

## Non-Goals

- No concrete Optuna, Ray Tune, W&B, MLflow, DVC, Hydra sweeper, or other
  external optimizer implementation.
- No default adaptive trial generation or optimizer control loop.
- No scheduler-owned trial cancellation or cancellation of already scheduled
  trials.
- No executor-forced active-stage termination as the default early-stop
  mechanism.
- No new core lifecycle statuses for `STOPPED` or `EARLY_STOPPED`.
- No domain metric parsing, objective semantics, or project-code imports in
  sweep core.
- No SLURM per-trial submission, bounded local concurrency, distributed sweep
  controller, retry policy, or rich failed-only rerun/filtering features.
- No sweep-specific bundle/export format. Sweeps remain ordinary runs that
  run-catalog and future v12 bundle tools can inspect.

## Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Do not introduce heavyweight runtime dependencies or optimizer dependencies.
- Treat authored sweep specs/configs as trusted project code.
- Keep config composition, stage execution, scheduler behavior, queue policy,
  run-store truth, artifact payload semantics, and catalog truth in their
  owning modules.
- Keep CLI as an outer layer over public Python APIs.
- Keep all persisted sweep records versioned, plain-data-compatible, and
  inspectable without project code imports.
- Run `make validate-pr` and `make test-summary` before each phase PR is
  prepared, or record why either command could not run.

## Design Principles

- **Ordinary runs first.** A trial is a normal Loom run with a `run_uri`, run
  directory, run-store status, provenance, artifact refs, and catalog visibility.
- **Provider contracts before provider ambition.** Define the generic
  provider/proposal and feedback seams now, but ship only deterministic
  grid/manual providers in v13.
- **Stable identity belongs to Loom.** Providers may supply external IDs in
  metadata, but Loom owns canonical `trial_id`, trial ordering, manifests, and
  run URI mapping.
- **Expansion and dispatch stay separate.** Providers produce trial proposals;
  dispatch adapters execute or submit planned trial run intents.
- **Control flow is explicit.** Cooperative early stop uses
  `context.stop_early(...)` over a typed signal and maps to cancellation reason
  metadata, not a failure or a new lifecycle state.
- **Collection is metadata-first.** v13 collects trial facts and artifact refs;
  concrete payload/metric extraction remains unsupported.
- **Future compatibility is recorded, not guessed.** Provider metadata,
  feedback records, coordination facts, and unsupported diagnostics leave room
  for plugins, external providers, remote artifact handling, and reliability
  policies without implementing those behaviors now.

## Key Design Choices

- Public sweep contracts are exported from `loom.pipeline.sweep`, with internal
  files free to change behind stable package exports. Avoid top-level
  `loom.__init__` re-exports in v13 unless a type is foundational and cheap to
  import.
- The provider API is an explicit contextful protocol. A provider receives
  planning context and yields `TrialProposal` or `TrialSpec` values. Finite
  count/materialization is optional. Feedback is a separate optional hook.
- The dispatch API is an explicit planned-trial intent protocol. Direct and
  queue dispatch adapters consume the same trial run intent/result records
  instead of inventing separate request shapes.
- Grid and manual providers are first-party implementations of the same public
  provider/proposal protocol, not special expansion paths.
- Loom owns canonical trial identity. Provider-supplied external IDs and
  optimizer facts are plain-data metadata.
- Versioned manifests are always written. Authority-backed coordination records
  are additional cross-run facts when an authority-backed coordination store is
  available.
- `context.stop_early(...)` is the ergonomic public API for cooperative early
  stop. It raises the same typed early-stop signal that policy helpers may raise
  directly.
- Early-stop persistence uses existing `CANCELLED` lifecycle state plus
  `LifecycleReason(code="early_stop")`. Sweep status derives `early_stopped`.
- Queue-backed dispatch enqueues finite planned trials as whole-run queue
  intents and returns submission results. Queue service/controller owns ongoing
  queue draining and cancellation behavior.
- Artifact extraction is represented by an adapter/request/result seam, but the
  default behavior is explicit unsupported diagnostics.
- CLI commands are thin wrappers. They do not own planning, expansion, dispatch,
  status, collection, or formatting-independent result semantics.

## Conflicts And Tradeoffs

- **Public provider contract vs. implementation simplicity:** adding provider
  protocols before the first concrete external optimizer increases Phase 1
  contract work, but prevents grid/manual code from becoming a one-off path.
- **Context helper vs. return-value early stop:** `context.stop_early(...)`
  requires execution lifecycle handling, but avoids broadening the `Stage.run`
  return type from output mappings into a general stage-outcome envelope.
- **Manifests plus coordination vs. one source:** manifests are portable and
  inspectable, while coordination records support authority-aware tooling and
  future controllers. Keeping both adds mapping work but preserves the correct
  ownership split.
- **Queue dispatch now vs. scheduler deferral:** queue dispatch is useful
  because queue service exists, but it must stay a dispatch adapter and avoid
  SLURM-specific or controller-daemon behavior.
- **Extraction seam vs. no extraction behavior:** publishing unsupported
  extraction records adds interface surface without immediate payload parsing,
  but it gives later artifact/materialization work a clear attachment point.
- **V12 compatibility vs. API timing:** v12 has a confirmed plan but pending
  phases. V13 can preserve ordinary-run compatibility now, but phase execution
  must recheck landed v12 APIs before using bundle/export details.

## Maintainability Assessment

The plan is maintainable if it keeps six boundaries sharp:

- `loom.pipeline.sweep` owns sweep behavior and contracts; `loom.cli.sweep`
  remains presentation only.
- Config override generation uses public config APIs and does not implement
  merge logic.
- Trial execution delegates to `PipelineRunner` or queue whole-run dispatch;
  sweep code does not execute stages directly.
- Status and collection read existing run, queue, catalog, or coordination
  state; they do not become a second source of lifecycle truth.
- Early-stop lifecycle handling stays narrow and structured.
- Provider, feedback, dispatch, extraction, and coordination interfaces are
  validated by contracts and fake adapters instead of speculative external
  dependencies.

The highest maintainability risks are public protocol sprawl, lifecycle
reason-mapping bugs, queue dispatch becoming scheduler policy, and collection
code drifting into domain metric interpretation.

## Extensibility Assessment

The v13 extensibility path is deliberate but narrow:

- V14 plugin discovery can load provider implementations later because v13
  defines plugin-free provider contracts first.
- Future Optuna-like adapters can map optimizer suggestions into proposals and
  consume plain-data observations through feedback records.
- V15/V16 external artifact and payload work can preserve artifact refs and
  later provide concrete extraction/materialization behavior.
- V19 retry, timeout, and event-sink policies can observe or extend lifecycle
  behavior without v13 claiming retry or executor cancellation semantics.
- Future bounded/distributed sweeps can reuse `SweepIdentity`,
  `TrialReference`, queue intents, trial feedback, and dispatch adapters.

The plan should not expose more public protocol surface than it can validate
with grid/manual, fake finite and unsized providers, fake queue dispatch,
synthetic run-state fixtures, and unsupported extraction diagnostics.

## Technical Debt Ledger

| Debt | Accepted For v13 Because | Revisit Trigger |
| --- | --- | --- |
| Provider and feedback protocols ship before concrete external optimizer adapters | User wants a stable public contract now, and concrete Optuna support is deferred | A real Optuna/Ray Tune/etc. adapter cannot express required state through provider context, proposal metadata, or feedback records |
| Artifact extraction interface exists before extraction behavior | User wants a future extraction seam while v13 must stay metadata-first and domain-neutral | A later artifact/materialization stage selects concrete safe plain-data extraction behavior |
| Early stop maps to `CANCELLED` plus reason rather than a new lifecycle state | Avoids broad lifecycle enum churn and treats early stop as controlled cancellation | Core consumers cannot reliably derive early-stop semantics from structured reason metadata |
| Queue-backed dispatch supports finite planned enqueue only | Keeps v13 cohesive with existing queue service without implementing controllers or scheduler policy | Bounded/distributed sweeps require queue cancellation, admission, or controller behavior beyond finite submission |
| V12 compatibility remains ordinary-run compatibility until v12 phases land | V12 plan is finalized but phase APIs may still be pending | V12 bundle/export APIs land and expose additional compatibility obligations for sweep manifests or collection |
| Rich rerun/filter/retry behavior is deferred | Roadmap defers failed-trial rerun policies and reliability owns retry | Users need failed-only reruns or retry policy before v19 reliability work |

## Validation Strategy

The plan must preserve the examples and validation matrix confirmed in the
planning notes.

| Example or behavior | Primary owning phases | Validation obligation |
| --- | --- | --- |
| Grid learning-rate/seed sweep | Phases 1, 2, 5 | Prove stable cartesian expansion, IDs, overrides, manifests, and CLI plan output. |
| Trial-count guard | Phase 2, Phase 5 | Prove generated sweeps over `100` trials fail unless explicitly overridden. |
| Manual ablation list | Phase 2 | Prove explicit trials, names, overrides, and manifests round-trip. |
| Failed trial visibility | Phase 3, Phase 5 | Prove sweeps run remaining trials and report failed sweep result when required trials fail. |
| External-generated manual trials | Phase 2 | Prove manual trial specs can represent Optuna-like externally generated lists without importing Optuna. |
| Adapter-first built-ins | Phases 1, 2 | Prove grid/manual satisfy the provider protocol. |
| Incremental-capable provider contract | Phase 1 | Prove fake finite and unsized providers work without requiring `len()`. |
| Adaptive feedback shape | Phase 1, Phase 3, Phase 4 | Prove feedback records carry status, lifecycle reason, artifact refs, and optional observations without domain metrics. |
| Cooperative early stopping hook | Phase 3, Phase 4, Phase 5 | Prove `context.stop_early(...)` maps to `CANCELLED` plus `early_stop` and derived `early_stopped`. |
| Generic artifact-ref collection | Phase 5 | Prove collection reads trial facts and artifact refs/metadata only. |
| Unsupported extraction request | Phase 1, Phase 5 | Prove extraction diagnostics are explicit and machine-readable. |
| Authority-backed coordination records | Phase 4 | Prove `SweepIdentity` and `TrialReference` creation/update with fake or SQLite coordination. |
| Queue-backed dispatch | Phase 4 | Prove planned trials enqueue as whole-run queue intents with stable trial/run mapping. |
| Queue status aggregation | Phase 4, Phase 5 | Prove status aggregates queue/run/coordination progress without controlling queue draining. |

Required suite categories:

- Package/import-boundary tests for sweep imports, CLI thinness, optional
  optimizer dependencies, and plugin-free behavior.
- Unit tests for value models, spec parsing, provider contracts, expansion,
  trial IDs, run URI mapping, manifests, diagnostics, and extraction defaults.
- Contract tests for provider/proposal protocols, finite capability, feedback
  records, dispatch adapters, extraction diagnostics, and coordination mapping.
- Integration tests for direct dispatch, early-stop lifecycle mapping, queue
  enqueue shape, status aggregation, collection, and CLI JSON envelopes.
- Limited e2e coverage for a small synthetic sweep workflow if current
  conventions support it.
- No default network, real cluster, external service, Optuna, or downstream
  project package tests.

## Implementation Workflow State

- Implementation-plan quality gate: passed on 2026-05-14
- Review pass: complete; local equivalent review run by managing Codex against
  `.codex/prompts/implementation-plan-review.md`
- Refinement pass: complete; minimal dispatch contract ownership clarified in
  Phase 1 and adapter implementation phases
- Confirmation review: complete; no blocking findings remain
- Automatic merge mode: enabled for later phase implementation
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Default phase base/target branch in this plan is `develop`. Each phase
  execution planner must recompute and record the actual stack predecessor and
  PR target before implementation; if an earlier phase is unmerged, branch from
  and target the recorded predecessor branch according to the stacked phase
  workflow.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `sweep-contracts-manifests` | merged | `codex/sweep-contracts-manifests` | [#151](https://github.com/samcantrill/loom/pull/151) | `loom.pipeline.sweep` contracts, models, manifests | Establish provider/proposal, dispatch, feedback, extraction, trial/sweep models, and manifest contracts | Package, unit, contract | Provider records, dispatch records, manifest round-trip, unsupported extraction |
| 2 | `grid-manual-planning` | pr_open | `codex/grid-manual-planning` | [#152](https://github.com/samcantrill/loom/pull/152) | `loom.pipeline.sweep` spec/grid/manual/planning | Implement grid/manual providers, deterministic expansion, IDs, guard, run URI mapping, and plan APIs | Unit, contract, narrow CLI smoke | Grid sweep, manual list, trial guard |
| 3 | `early-stop-direct-dispatch` | pending | `codex/early-stop-direct-dispatch` | pending | `loom.pipeline.context`, execution lifecycle, sweep runner/dispatch | Implement cooperative early stop, direct dispatch, failure policy, and compatible resume | Unit, contract, integration | Early stop, failed trial visibility, sequential run |
| 4 | `coordination-queue-status` | pending | `codex/coordination-queue-status` | pending | sweep coordination/dispatch/status and queue integration seams | Record authority coordination, enqueue finite queue trials, and aggregate status | Contract, integration | Coordination records, queue dispatch/status |
| 5 | `sweep-collection-cli-hardening` | pending | `codex/sweep-collection-cli-hardening` | pending | sweep collection, CLI, docs, final hardening | Implement collection, unsupported extraction reporting, `loom sweep` CLI, docs, and final validation | Package, unit, contract, integration, limited e2e | Collection, CLI workflow, final gate |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Plan quality gate | Workflow requirement | Local review, one refinement pass, and confirmation review completed on 2026-05-14 before Phase 1 starts | resolved |
| Roadmap planning blockers | `docs/roadmap/stage-13/planning.md` | None after final planning confirmation | resolved |

## Plan Quality Gate

- Status: passed
- Gate date: 2026-05-14
- Reviewer: managing Codex local review using the
  `.codex/prompts/implementation-plan-review.md` criteria. No separate reviewer
  subagent was used because this turn did not request delegated agent work.
- Review pass: complete; planning readiness, maintainability, extensibility,
  conflicting design choices, technical debt, test strategy, and reviewability
  were checked.
- Refinement pass: used; the plan now makes Phase 1 own the minimal dispatch
  request/result contract alongside provider, feedback, extraction, and
  manifest contracts so direct and queue adapters cannot drift.
- Confirmation review: complete; no blocking findings remain after the
  refinement.
- Budget status: review used, refinement used, confirmation used.
- Planning-readiness dependencies:
  - `docs/roadmap/stage-13/planning.md` records final planning confirmation.
  - Design-safety review passed with no blockers.
  - No unresolved `blocked` or `needs discussion` planning decisions remain.
  - Examples, validation strategy, and phase shaping are specific enough to
    draft phases.
- Gate result:
  - Ready for Phase 1 execution planning.
  - No product implementation may begin until the Phase 1 execution plan exists
    and records branch, worktree, stack predecessor, target branch, scope,
    acceptance criteria, suite obligations, design impact, future
    compatibility, alternatives rejected, debt, reviewability, and budget
    status.

Findings from the review pass:

| Severity | Location | Finding | Resolution |
| --- | --- | --- | --- |
| Concern | `Key Design Choices`, Phase 1, Phase 3, Phase 4 | The draft made provider, feedback, extraction, and manifest contracts explicit in Phase 1, but left the dispatch contract implied until direct and queue dispatch implementation phases. That could let direct and queue adapters invent subtly different trial request/result shapes. | Phase 1 now owns the minimal planned-trial dispatch request/result contract. Phases 3 and 4 are implementation phases over that contract. |
| Note | `Implementation Workflow State`, phase branch metadata | The phase tables list `develop` as the default base/target for all phases, but stacked continuation may require a later phase to branch from and target an unmerged predecessor. | The workflow state records `develop` as the default only and requires each phase execution planner to recompute and record the actual stack predecessor and PR target before implementation. |

The confirmation review verified that the plan preserves the final planning
artifact's provider/proposal boundary, optional finite-provider capability,
adaptive feedback record shape, cooperative early-stop decision, `CANCELLED`
plus `early_stop` lifecycle mapping, manifest plus authority-coordination
split, queue enqueue-only dispatch boundary, metadata-first collection, and v12
ordinary-run compatibility guardrail.

## Phased Implementation

### Phase 1: Sweep Contracts And Manifests

- Status: merged
- Slug: `sweep-contracts-manifests`
- Branch: `codex/sweep-contracts-manifests`
- Worktree: `/home/samcantrill/work/loom-worktrees/sweep-contracts-manifests`
- PR: [#151](https://github.com/samcantrill/loom/pull/151)
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

#### Scope

- Goal: establish public sweep contracts and persisted record schemas without
  expansion implementation, execution behavior, queue behavior, or CLI commands.
- Files/modules owned:
  - `src/loom/pipeline/sweep/__init__.py`
  - `src/loom/pipeline/sweep/spec.py`
  - `src/loom/pipeline/sweep/trials.py`
  - `src/loom/pipeline/sweep/manifest.py`
  - `src/loom/pipeline/sweep/providers.py`
  - `src/loom/pipeline/sweep/dispatch.py`
  - `src/loom/pipeline/sweep/feedback.py`
  - `src/loom/pipeline/sweep/extraction.py`
  - `src/loom/pipeline/sweep/errors.py`
  - matching package/unit/contract tests
- Behavior implemented:
  - Public value models for sweep specs, manual trial specs, trial specs,
    trial proposals, sweep plans, provider identity/metadata, trial/run URI
    mapping, and extraction diagnostics.
  - Contextful provider/proposal protocol with optional finite capability.
  - Minimal dispatch request/result records for planned trial run intents,
    submission results, and direct execution results.
  - Feedback/observation records carrying plain-data outcome/status/reason and
    artifact refs/metadata without domain metric semantics.
  - Versioned sweep/trial manifest models with strict schema/version handling
    and explicit extension/metadata fields.
  - Unsupported/not-implemented extraction result and diagnostics.
- Decisions applied:
  - Provider protocol is explicit and contextful.
  - Dispatch protocol is separate from generation and shared by direct and
    queue-backed adapters.
  - Finite materialization/count is optional.
  - Loom owns canonical `trial_id` and run URI mapping.
  - Extraction is interface-only with unsupported behavior.
- Examples or docs covered:
  - Provider records.
  - Manifest round-trip.
  - Unsupported extraction request.
- Out of scope:
  - Grid/manual expansion implementation.
  - `context.stop_early(...)` execution lifecycle changes.
  - Direct or queue dispatch implementations.
  - Status aggregation and collection implementation.
  - CLI commands.
  - Plugin discovery or concrete external providers.
- Dependencies:
  - Existing serialization, artifact ref, run URI vocabulary, and status value
    objects.

#### Tasks

- Create the sweep package and import-light public exports.
- Define sweep/trial/provider/feedback/extraction value models.
- Define provider/proposal and optional finite capability protocols.
- Define minimal planned-trial dispatch request/result records.
- Define manifest versioning, round-trip, and compatibility diagnostics.
- Add unsupported extraction diagnostics and tests.
- Add package/import-boundary checks showing no optional optimizer or CLI import
  dependency.

#### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted package/import tests | Prove sweep contracts are import-light and optimizer-free | yes |
| Targeted unit tests under `tests/unit/loom/pipeline/sweep/` | Model validation and manifest round-trip | yes |
| Targeted contract tests | Provider protocol, finite capability, dispatch request/result records, feedback, unsupported extraction | yes |
| `make validate-pr` | PR gate | yes |
| `make test-summary` | PR evidence | yes |

#### Acceptance Evidence

- Behavior evidence: records round-trip through plain data and reject invalid
  schema versions.
- Design-decision evidence: provider protocol does not require `len()`,
  dispatch request/result records are adapter-neutral, and extraction returns
  structured unsupported diagnostics.
- Future-roadmap compatibility evidence: provider metadata and feedback records
  can represent future external provider facts without importing one.
- Interface, adapter, or protocol reuse evidence: fake finite and unsized
  providers and fake direct/queue dispatch records satisfy contract tests.
- Documentation evidence: public contracts are documented in module docstrings
  or feature docs where required by the phase plan.
- Domain-neutrality evidence: no metric/objective terms beyond generic
  observations and metadata.

#### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: used for expanded-path draft/refine
- Implementation/refinement budget: used as manager-local completion and
  pre-submit correction after executor checkpoint
- PR review budget: used by manager pre-submit review
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed
- Merge record: complete; squash merged to `develop` as
  `6facf9d6e5d94d56e3073f787fde6b6ea44a091d` on 2026-05-14 after CI passed.

#### Risks And Stop Conditions

- Risks:
  - Protocol surface can become too broad before grid/manual prove it.
  - Manifest schemas can overfit to built-ins before built-ins exist.
- Stop conditions:
  - Provider protocol cannot represent both fake finite and fake unsized
    providers without special cases.
  - Records require optional optimizer, queue, CLI, or project-code imports.
- Assumptions:
  - Structural protocols and plain-data records are sufficient for v13.

#### Completion Summary

- Implementation: Added import-light sweep provider/proposal, dispatch,
  feedback, extraction, trial, and versioned manifest contract records under
  `loom.pipeline.sweep`.
- Validation: Targeted package tests passed (`45 passed`), targeted sweep
  unit/contract tests passed (`16 passed`), targeted Ruff passed, `make
  validate-pr` passed, and `make test-summary` passed.
- PR: [#151](https://github.com/samcantrill/loom/pull/151), targeting
  `develop` from `codex/sweep-contracts-manifests`.
- Merge: Squash merged [#151](https://github.com/samcantrill/loom/pull/151)
  into `develop` as `6facf9d6e5d94d56e3073f787fde6b6ea44a091d` on
  2026-05-14. Pre-merge verification confirmed `baseRefName=develop`,
  `headRefName=codex/sweep-contracts-manifests`, `mergeStateStatus=CLEAN`,
  and GitHub CI `checks` completed successfully. Remote branch
  `codex/sweep-contracts-manifests` was deleted after merge because no
  successor branch depended on it.
- Follow-up: Phase 2 owns grid/manual planning behavior over these contracts.

### Phase 2: Grid And Manual Planning

- Status: pr_open
- Slug: `grid-manual-planning`
- Branch: `codex/grid-manual-planning`
- Worktree: `/home/samcantrill/work/loom-worktrees/grid-manual-planning`
- PR: [#152](https://github.com/samcantrill/loom/pull/152)
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

#### Scope

- Goal: implement deterministic finite sweep planning through first-party grid
  and manual providers over the Phase 1 contracts.
- Files/modules owned:
  - `src/loom/pipeline/sweep/spec.py`
  - `src/loom/pipeline/sweep/grid.py`
  - `src/loom/pipeline/sweep/manual.py`
  - `src/loom/pipeline/sweep/trials.py`
  - `src/loom/pipeline/sweep/manifest.py`
  - planning helpers in `src/loom/pipeline/sweep/runner.py` only if needed
  - matching tests
- Behavior implemented:
  - Parse/normalize trusted sweep specs for grid and manual modes.
  - Expand grid axes deterministically into stable ordered trial specs.
  - Expand explicit manual trial lists with stable IDs and optional names.
  - Apply default generated-trial guard of `100` with explicit override.
  - Produce run URI mappings while preserving separate sweep-local `trial_id`.
  - Write/copy authored spec and generated manifests in plan-only APIs.
- Decisions applied:
  - Grid/manual are first-party providers.
  - Larger generated sweeps require explicit opt-in.
  - Config override semantics use existing override syntax/helpers.
- Examples or docs covered:
  - Grid learning-rate/seed sweep.
  - Trial-count guard.
  - Manual ablation list.
  - External-generated manual trial list.
- Out of scope:
  - Executing trials.
  - Early-stop lifecycle behavior.
  - Queue dispatch.
  - Collection and full CLI.
- Dependencies:
  - Phase 1 contracts and manifest models.
  - Existing config override parsing/formatting.

#### Tasks

- Implement grid provider expansion and ordering.
- Implement manual provider expansion and validation.
- Implement stable trial ID/name/path/run URI mapping helpers.
- Implement plan generation and manifest write/read paths.
- Add guard errors and diagnostics for excessive generated trial counts.
- Add tests for deterministic ordering, ID stability, overrides, manifests,
  compatibility checks, and plan-only behavior.

#### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted sweep unit tests | Grid/manual parsing, expansion, IDs, guard | yes |
| Targeted contract tests | Built-ins satisfy provider protocol | yes |
| Narrow CLI smoke if parser shell exists | Verify plan output can be wrapped later without changing API | no |
| `make validate-pr` | PR gate | yes |
| `make test-summary` | PR evidence | yes |

#### Acceptance Evidence

- Behavior evidence: identical specs produce identical trial order, IDs,
  overrides, and run URI mapping.
- Design-decision evidence: grid/manual go through provider protocol.
- Future-roadmap compatibility evidence: manual trials can represent
  externally generated Optuna-like trial lists without dependency imports.
- Interface, adapter, or protocol reuse evidence: finite capability exposed
  only for finite providers.
- Documentation evidence: examples or feature docs reflect planning behavior.
- Domain-neutrality evidence: axes and observations are generic config facts.

#### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: used for expanded-path draft/refine in
  `docs/roadmap/stage-13/phases/grid-manual-planning.md`
- Implementation/refinement budget: used locally to address Pyright typing
  findings after the first full validation run
- PR review budget: unused
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed
- Merge record: pending

#### Risks And Stop Conditions

- Risks:
  - Override generation could accidentally duplicate config merge semantics.
  - Trial naming could leak unstable paths into public identity.
- Stop conditions:
  - Existing config APIs cannot represent required trial overrides without a
    new merge language.
  - Manifest compatibility rules cannot distinguish compatible resume from
    incompatible plans.
- Assumptions:
  - Authored sweep specs are trusted project code.

#### Completion Summary

- Implementation: Added trusted grid/manual sweep spec records, first-party
  finite providers, deterministic proposal-to-trial materialization, default
  generated-trial guard, run URI mapping, plan-only manifest/spec writes, and
  compatible readback diagnostics.
- Validation: Targeted Phase 2 tests passed (`70 passed`); `make validate-pr`
  passed after local Pyright fixes; `make test-summary` passed.
- PR: [#152](https://github.com/samcantrill/loom/pull/152), targeting
  `develop` from `codex/grid-manual-planning`.
- Merge:
- Follow-up:

### Phase 3: Early Stop And Direct Dispatch

- Status: pending
- Slug: `early-stop-direct-dispatch`
- Branch: `codex/early-stop-direct-dispatch`
- Worktree: `/home/samcantrill/work/loom-worktrees/early-stop-direct-dispatch`
- PR: pending
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

#### Scope

- Goal: implement cooperative early-stop lifecycle mapping and direct
  sequential sweep dispatch through ordinary `PipelineRunner` runs.
- Files/modules owned:
  - `src/loom/pipeline/context.py`
  - `src/loom/pipeline/execution/lifecycle.py`
  - `src/loom/pipeline/execution/runner.py`
  - executor handling where needed, especially local execution paths
  - `src/loom/pipeline/sweep/early_stopping.py`
  - `src/loom/pipeline/sweep/dispatch.py`
  - `src/loom/pipeline/sweep/runner.py`
  - matching tests
- Behavior implemented:
  - `context.stop_early(...)` helper that raises a typed early-stop signal with
    message and plain-data detail.
  - Policy/helper functions that can raise the same signal directly.
  - Execution handling that catches the typed signal before generic failure
    handling and records controlled cancellation with
    `LifecycleReason(code="early_stop")`.
  - Direct sequential dispatch adapter that builds one `RunRequest` per trial
    from Phase 1 planned-trial dispatch records and delegates to
    `PipelineRunner`.
  - Failure policy that runs remaining trials and returns failed sweep result
    if any required trial failed.
  - Explicit compatible resume/open-existing behavior against manifests.
- Decisions applied:
  - Do not broaden `Stage.run()` return type.
  - Do not add new core lifecycle status enum values.
  - Do not cancel scheduled trials or force-kill executor work by default.
- Examples or docs covered:
  - Failed trial visibility.
  - Cooperative early stopping hook.
  - Sequential run workflow.
- Out of scope:
  - Queue dispatch.
  - Authority-backed coordination projection.
  - Full status aggregation.
  - CLI commands beyond any narrow test hooks required.
- Dependencies:
  - Phase 1 contracts and Phase 2 planning/run URI mapping.
  - Existing runner, local executor, status, and lifecycle helpers.

#### Tasks

- Add typed early-stop signal and context helper.
- Add lifecycle helpers for cancelled run/stage records with structured reason.
- Update local/runner execution paths to handle early-stop signal separately
  from failures.
- Implement direct dispatch adapter and sweep run result models over the
  Phase 1 dispatch records.
- Implement compatible resume/open-existing checks at the sweep manifest level.
- Add tests for success, failure continuation, early stop, incompatible
  manifests, and run request metadata.

#### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted context/lifecycle tests | Early-stop helper and reason mapping | yes |
| Targeted executor/runner tests | Early-stop is not generic failure | yes |
| Targeted sweep runner tests | Direct dispatch, failure continuation, resume checks | yes |
| Integration tests with synthetic stages | Ordinary runs and early stops through runner | yes |
| `make validate-pr` | PR gate | yes |
| `make test-summary` | PR evidence | yes |

#### Acceptance Evidence

- Behavior evidence: a synthetic stage can call `context.stop_early(...)` and
  produce `CANCELLED` plus `early_stop` reason.
- Design-decision evidence: `Stage.run()` still returns output mappings and
  early stop does not require return-value envelopes.
- Future-roadmap compatibility evidence: retry/timeout/scheduler cancellation
  semantics remain deferred and unclaimed.
- Interface, adapter, or protocol reuse evidence: direct dispatch consumes
  Phase 1 planned-trial dispatch records, not provider internals.
- Documentation evidence: early-stop semantics are documented for users.
- Domain-neutrality evidence: helper accepts generic message/detail, not metric
  names or objectives as required fields.

#### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: unused
- Pre-submit blocker gate: pending
- Merge record: pending

#### Risks And Stop Conditions

- Risks:
  - Early-stop signal could be swallowed by executor or worker layers as a
    generic failure.
  - Cancellation reason metadata may not be consistently visible to status and
    catalog readers.
- Stop conditions:
  - Execution model cannot represent controlled cancellation without broad
    lifecycle refactor.
  - Handling early-stop would require adding `STOPPED` or `EARLY_STOPPED` core
    statuses.
- Assumptions:
  - Existing status/lifecycle reason metadata is sufficient.

#### Completion Summary

- Implementation:
- Validation:
- PR:
- Merge:
- Follow-up:

### Phase 4: Coordination, Queue Dispatch, And Status

- Status: pending
- Slug: `coordination-queue-status`
- Branch: `codex/coordination-queue-status`
- Worktree: `/home/samcantrill/work/loom-worktrees/coordination-queue-status`
- PR: pending
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

#### Scope

- Goal: connect planned/running sweeps to authority-backed coordination, queue
  finite-trial submission, and aggregate sweep status read models.
- Files/modules owned:
  - `src/loom/pipeline/sweep/coordination.py`
  - `src/loom/pipeline/sweep/dispatch.py`
  - `src/loom/pipeline/sweep/status.py`
  - queue projection helpers in sweep modules
  - matching tests
- Behavior implemented:
  - Create/update `SweepIdentity` and `TrialReference` whenever an
    authority-backed coordination store is available.
  - Map trial states to coordination states without copying per-run lifecycle
    truth.
  - Queue dispatch adapter that projects finite planned trial run intents into
    whole-run queue enqueue requests through the Phase 1 dispatch records.
  - Queue dispatch returns submission results and does not drain or control the
    queue loop.
  - Sweep status aggregates manifests plus run/queue/coordination read models
    into counts and trial summaries, including derived `early_stopped`.
- Decisions applied:
  - Manifests are always written.
  - Authority coordination facts are additional cross-run indexes.
  - Queue service/controller owns ongoing scheduling and cancellation.
- Examples or docs covered:
  - Authority-backed coordination records.
  - Queue-backed dispatch.
  - Queue status aggregation.
- Out of scope:
  - Direct dispatch behavior already implemented in Phase 3 except integration
    adjustments.
  - Bounded local concurrency.
  - Distributed controllers.
  - Scheduled-trial cancellation.
  - SLURM per-trial submission logic.
- Dependencies:
  - Phases 1 through 3.
  - Existing queue models/service and workspace coordination store.

#### Tasks

- Implement coordination projection helpers for sweep/trial records.
- Add authority-backed coordination integration to runner/dispatch flow.
- Implement queue-backed dispatch adapter over finite plans and the Phase 1
  dispatch records.
- Implement status models and aggregation from manifests, run state, queue
  state, and coordination state.
- Add tests with fake/in-memory and SQLite coordination stores.
- Add tests with fake queue service/repository showing enqueue shape and
  progress readback.

#### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted coordination contract/integration tests | Sweep/trial record creation and updates | yes |
| Targeted queue dispatch tests | Enqueue shape and submission results | yes |
| Targeted status tests | Outcome counts, queue states, early-stopped derivation | yes |
| Import-boundary tests | Queue does not import sweep internals and sweep does not own queue loop | yes |
| `make validate-pr` | PR gate | yes |
| `make test-summary` | PR evidence | yes |

#### Acceptance Evidence

- Behavior evidence: authority-backed sweeps record `SweepIdentity` and
  `TrialReference`; queue dispatch enqueues finite planned trials.
- Design-decision evidence: sweep status reads queue/run/coordination state
  without controlling queue draining.
- Future-roadmap compatibility evidence: coordination records can support later
  distributed controllers and resource limits.
- Interface, adapter, or protocol reuse evidence: queue dispatch consumes
  Phase 1 trial run intent records through the dispatch adapter boundary.
- Documentation evidence: queue-backed behavior is documented as submit-and-
  status, not controller mode.
- Domain-neutrality evidence: status contains generic lifecycle and artifact
  facts only.

#### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: unused
- Pre-submit blocker gate: pending
- Merge record: pending

#### Risks And Stop Conditions

- Risks:
  - Queue enqueue request shape may not carry enough trial metadata without
    widening queue models.
  - Status aggregation could accidentally privilege one backend as truth.
- Stop conditions:
  - Queue service cannot represent whole-run trial intents with stable metadata
    without queue-policy changes outside v13.
  - Coordination schema cannot represent required sweep/trial mapping.
- Assumptions:
  - Queue run intent metadata can carry sweep/trial facts.

#### Completion Summary

- Implementation:
- Validation:
- PR:
- Merge:
- Follow-up:

### Phase 5: Collection, CLI, Docs, And Hardening

- Status: pending
- Slug: `sweep-collection-cli-hardening`
- Branch: `codex/sweep-collection-cli-hardening`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/sweep-collection-cli-hardening`
- PR: pending
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

#### Scope

- Goal: complete user-facing collection, CLI commands, docs, and final
  validation for deterministic sweeps.
- Files/modules owned:
  - `src/loom/pipeline/sweep/collection.py`
  - `src/loom/pipeline/sweep/extraction.py`
  - `src/loom/pipeline/sweep/status.py`
  - `src/loom/cli/sweep.py`
  - `src/loom/cli/main.py`
  - docs and CLI/integration/e2e tests
- Behavior implemented:
  - Collection of trial facts, override values, run statuses, and artifact
    refs/metadata without loading artifact payloads.
  - Explicit unsupported/not-implemented diagnostics for extraction requests.
  - `loom sweep plan`, `loom sweep run`, `loom sweep status`, and
    `loom sweep collect` with text and JSON output.
  - CLI exit-code behavior for validation errors, failed sweeps, unsupported
    extraction, and successful queue submission/status.
  - Documentation for sweep specs, provider/future-provider contract,
    early-stop helper, direct/queue dispatch, status outcomes, and collection.
  - Final import-boundary and validation hardening.
- Decisions applied:
  - CLI is thin and does not duplicate sweep business logic.
  - Collection remains metadata/artifact-ref oriented.
  - V12 compatibility is ordinary-run compatibility, not a sweep export format.
- Examples or docs covered:
  - Generic artifact-ref collection.
  - Unsupported extraction request.
  - CLI workflow.
  - Final validation gate.
- Out of scope:
  - Concrete extraction adapters.
  - Concrete optimizer providers.
  - Rich rerun/filtering/retry commands.
  - Sweep-specific bundle/export commands.
- Dependencies:
  - Phases 1 through 4.
  - Current CLI patterns and formatting helpers.
  - Current v12 APIs if any have landed; otherwise ordinary-run compatibility
    only.

#### Tasks

- Implement collection models and metadata/artifact-ref collection API.
- Implement extraction request handling with unsupported diagnostics.
- Add CLI parser registration and handlers.
- Add text/JSON output formatting.
- Add docs/examples for grid, manual, early stop, queue dispatch, status, and
  collection.
- Recheck current v12 landed APIs and document compatibility without creating
  sweep-specific export behavior.
- Run final import-boundary and validation sweeps.

#### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted collection tests | Trial facts, overrides, artifact refs, unsupported extraction | yes |
| Targeted CLI tests | Text/JSON commands and exit codes | yes |
| Integration/e2e synthetic workflow | Plan/run/status/collect happy path where practical | yes |
| Package/import-boundary tests | CLI thinness and no optional optimizer imports | yes |
| `make validate-pr` | PR gate | yes |
| `make test-summary` | PR evidence | yes |

#### Acceptance Evidence

- Behavior evidence: synthetic users can plan, run or enqueue, inspect status,
  and collect metadata/artifact refs.
- Design-decision evidence: CLI calls public sweep APIs and does not parse
  manifests/run stores directly when APIs exist.
- Future-roadmap compatibility evidence: v12 compatibility is preserved through
  ordinary run/catalog/artifact refs and does not introduce sweep export.
- Interface, adapter, or protocol reuse evidence: unsupported extraction and
  provider/dispatch contracts remain stable.
- Documentation evidence: docs cover supported behavior, deferrals, and
  examples.
- Domain-neutrality evidence: collection does not parse metrics or import
  project codecs.

#### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: unused
- Pre-submit blocker gate: pending
- Merge record: pending

#### Risks And Stop Conditions

- Risks:
  - CLI scope could expand into rerun/filter/retry behavior.
  - Collection could drift into metric semantics.
  - v12 APIs may land during v13 planning and require docs adjustments.
- Stop conditions:
  - Current CLI architecture cannot host `loom sweep` without large unrelated
    refactor.
  - Collection requires loading artifact payloads or importing project code for
    baseline behavior.
- Assumptions:
  - Text/JSON CLI patterns from existing commands are reusable.

#### Completion Summary

- Implementation:
- Validation:
- PR:
- Merge:
- Follow-up:

## Cross-Phase Review Notes

- Phase 1 must not implement grid/manual expansion, execution, queue behavior,
  or CLI commands early.
- Phase 1 must define the minimal dispatch request/result records consumed by
  later direct and queue adapters, but must not implement dispatch behavior.
- Phase 2 must prove grid/manual through the provider protocol and must not
  implement execution behavior early.
- Phase 3 must land early-stop lifecycle mapping before status derives
  `early_stopped`.
- Phase 3 must not broaden `Stage.run()` to return `StageOutcome`.
- Phase 4 must not turn sweep execution into a queue controller or add
  scheduled-trial cancellation.
- Phase 5 must not duplicate business logic in CLI or introduce metric
  extraction behavior.
- Every phase execution plan must record design impact, future compatibility,
  alternatives rejected, debt introduced, reviewability, and phase budget
  status before implementation starts.
- Full PR preparation for every phase must run or justify `make validate-pr`
  and `make test-summary`.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Dispatch contract ownership was implied too late | concern | Phase 1 now owns minimal planned-trial dispatch request/result records; direct and queue behavior remain in Phases 3 and 4 | resolved |
| Stacked branch targeting must not be hard-coded from phase table defaults | note | Workflow state records `develop` as default only and requires each phase execution plan to recompute branch, stack predecessor, and PR target | resolved |

Gate result:

- Status: passed on 2026-05-14
- Review evidence: local equivalent review checked planning readiness,
  traceability, design-safety carry-forward, maintainability, extensibility,
  conflicting design choices, technical debt, validation strategy, phase
  reviewability, and stack workflow metadata.
- Accepted risks: provider/feedback/dispatch protocols may need widening when
  the first concrete external optimizer adapter is designed; early-stop signal
  handling touches execution lifecycle and must be tested before status uses
  derived `early_stopped`; queue dispatch is finite enqueue-only until a later
  controller phase.
- Revisit triggers: concrete external provider cannot express proposals or
  observations through v13 records; structured `early_stop` reason cannot be
  read reliably by status/catalog surfaces; queue service cannot carry stable
  sweep/trial facts in whole-run intents; v12 bundle/export APIs land with
  additional compatibility obligations.

## Final Approval

- Approval status: ready for Phase 1 execution planning
- User approval: approved on 2026-05-14.
- Approved scope: five-phase deterministic sweep plan covering contracts and
  manifests, grid/manual planning, cooperative early stop plus direct dispatch,
  authority/queue/status integration, and collection/CLI/docs hardening.
- Accepted risks: same as the Plan Quality Gate accepted risks above.
- Deferred items: concrete optimizer adapters, default adaptive generation,
  scheduled-trial cancellation, executor-forced active-stage termination, new
  core lifecycle statuses, SLURM per-trial submission, bounded local
  concurrency, distributed controllers, rich rerun/filter/retry policies, and
  metric or artifact-payload extraction.
