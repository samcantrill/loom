# Roadmap Stage 18 Implementation Plan: HPC Container Execution

Status: in_progress
Roadmap stage: `v18`
Planning document: `docs/roadmap/stage-18/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 5 pr_open
Blockers:

- None. Implementation-plan quality gate passed on 2026-05-17 after manager
  review found no product-design blockers, one bounded refinement refreshed
  stale Stage 17 source evidence, and manager confirmation verified Phase 1
  may proceed from the landed Stage 17 contracts.

## Summary

- Goal: implement HPC container execution by adding shared Docker/Apptainer
  dynamic build targets, local foreground build/reuse, Apptainer/Singularity
  direct execution, and SLURM plus Apptainer composition through existing Loom
  worker, run-store, scheduler, diagnostics, provenance, and validation
  machinery.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-18/planning.md`; shared build targets, SIF
  construction, local build service, direct Apptainer execution, and SLURM
  wrapping are locked.
- Approved behavior: users configure named container build targets at
  run/profile scope, Loom builds or reuses Docker image refs and Apptainer SIF
  refs locally, stages run through the normal prepared-worker contract, and
  SLURM scripts submit resolved Apptainer execution commands without hidden
  build steps.
- Source behavior confirmation: complete in the planning artifact after user
  approval of functionality, behavior, examples, validation strategy, phase
  shaping, and the functionality/code-structure/usage readback.
- Key design constraints: optional Docker/Apptainer/SLURM imports, CLI-backed
  runtimes only, no Python Docker or Apptainer SDK, fake/local/offline default
  validation, explicit and redacted metadata, clean Apptainer environment by
  default, no per-stage recipe requirement, no hidden batch-script builds, no
  rank/MPI orchestration, no registry/auth/site-service policy, and no
  security-sandbox claim.
- Source design-agreement gate: confirmed. Use executor-owned shared
  `container_build` records, runtime-specific Docker/Apptainer builders,
  Apptainer/Singularity command builders and executor, existing SLURM argv
  rendering/submission composition, selected-executor preflight, and stable
  future-roadmap facts for Stage 19-21.
- Future-roadmap impact: Stage 19 can distinguish build, launch, process,
  worker, scheduler, timeout-capability, and failure facts; Stage 20 can
  project build/runtime/scheduler facts into events; Stage 21 can reason about
  build evidence, logs, bind-mounted roots, and cleanup candidates without
  treating container outputs as authority state.
- Reusable interface, adapter, or protocol assumptions: shared
  `container_build` request/result/output-ref records stay import-light and
  runtime-neutral; command runners remain adapter-local; descriptors claim
  adapter namespaces and resource capabilities without importing runtime
  behavior; SLURM composition is an argv/script wrapping point, not a new
  scheduler executor.
- Examples covered: named build target reuse, Apptainer SIF build, local build
  service, complete `container_build` namespace override, build evidence versus
  output refs, direct Apptainer execution, SLURM plus Apptainer dry-run/live,
  submit-side build ordering, clean environment defaults, and cheap preflight.
- Source phase shaping: five phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-17.
- Out of scope: external/site build services, Apptainer remote build,
  registry/auth helpers, automatic image conversion beyond explicit build
  sources, Docker Compose, Kubernetes, image publishing, whole-controller
  container mode, path translation, rank/MPI orchestration, site module policy,
  broad retry/timeout/transaction policy, cleanup/retention/GC policy, and
  real runtime/cluster requirements in default tests.

## Goal

Stage 18 should let the same Loom pipeline run selected stage attempts inside
Apptainer/Singularity containers on local or SLURM-backed HPC systems while
preserving Loom's existing execution contract. The controller still prepares
stage worker requests, the worker still writes normal results, and stores,
provenance, diagnostics, and submitted-operation records remain the source of
truth.

The stage also adds the shared build layer requested during planning: users
define reusable container build targets once, Loom builds or reuses those
targets locally, and Docker or Apptainer execution runs from explicit output
refs. The build layer provides recorded, inspectable provenance without making
Loom a registry, package manager, site scheduler, or container recipe
generator.

## Context

Current source already has the non-container machinery Stage 18 must compose:

- `loom.pipeline.execution` owns prepared stage-worker requests, runner
  lifecycle, worker results, output handling, and executor result integration.
- `loom.pipeline.executors.subprocess` demonstrates the prepared-worker
  pattern: construct argv, launch through an injectable runner, read the
  worker result, and normalize launch/process/worker conflicts.
- `loom.pipeline.executors.slurm` owns deterministic dry-run planning,
  `SlurmCommandArgv`, SBATCH resource mapping, script rendering,
  submitted-operation manifests, fake command runners, status, cancel, and live
  submission.
- `loom.pipeline.runtime` owns runtime options, adapter options, descriptor
  namespaces, and capability diagnostics.
- `loom.diagnostics.preflight` owns selected preflight groups and stable check
  IDs for runtime, executor, resources, filesystem, artifacts, and SLURM.
- `loom.provenance` already has a generic container mapping in provenance
  records that later container execution facts can populate safely.

Stage 17 is the Docker prerequisite. Its landed source records shared
`container` execution records and Docker executor behavior. Phase 1 execution
planning refreshed current source from `origin/develop` before code changes and
found the prerequisite contracts present and compatible.

Source refresh result for Phase 1:

- `src/loom/pipeline/executors/containers.py` exists and owns import-light
  shared container execution records.
- `src/loom/pipeline/executors/docker/` exists and owns Docker command and
  executor behavior.
- No Apptainer/Singularity executor module exists yet.
- Pipeline specs and runtime request models still keep container, Docker, and
  Apptainer choices in adapter namespaces rather than semantic stage specs.
- Existing SLURM code is available and remains the scheduler authority.

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-18/planning.md`
- Functionality and behavior baseline: complete. The notes lock reusable
  Docker/Apptainer build targets, local foreground build service, explicit SIF
  construction, direct Apptainer/Singularity execution, SLURM plus Apptainer
  composition, clean environment defaults, output/evidence separation, stable
  preflight, fake/default validation, and deferrals.
- Design-safety review: passed on 2026-05-17 with no blockers. The review
  recorded guardrails for `container_build` whole-namespace replacement,
  explicit output refs, submit-side build ordering before SLURM rendering or
  live submission, and clean Apptainer environment defaults.
- Examples and validation strategy: complete. Default validation uses fake
  builders/runners and deterministic scripts; real Docker, Apptainer/SIF build,
  and SLURM smoke remain opt-in.
- Phase shaping: complete. Five reviewable phases are recorded below.
- Implementation readiness blockers from planning: none for planning. Stage 17
  source refresh is a required first drafting/phase-planning action and an
  accepted risk.
- Remaining workflow blocker: none.
- Accepted risks and revisit triggers:
  - Stage 17 source was absent at draft time but is now present on
    `origin/develop`; Phase 1 proceeds by extending
    `loom.pipeline.executors.containers`. Revisit only if a later rebase
    materially changes those landed contracts.
  - `container_build` uses current adapter namespace replacement semantics.
    Revisit when users need per-target overlay, deletion, or typed merge.
  - Build evidence is run-local and output refs are explicit; no global cache
    or image-lock policy. Revisit when external/site build services or image
    locks are designed.
  - Path parity is fail-closed. Revisit when remote stores, non-shared
    filesystems, or explicit path translation become required.
  - Real cluster/runtime validation remains optional. Revisit if release policy
    requires live environment evidence.

## Desired Outcome

When all phases are complete:

- A user can define one named container build target and reuse it across
  multiple stages without creating one container recipe per stage.
- `container_build` records can represent Docker and Apptainer build targets,
  source descriptions, policies, requests, results, output refs, redacted
  commands, and build evidence without importing runtime-specific behavior.
- A local foreground build service can build, reuse, fail, and validate Docker
  image refs and Apptainer SIF refs through fakeable adapters.
- Apptainer/Singularity command construction supports deterministic
  `apptainer build` and `apptainer exec` argv, bind mounts, workdir, explicit
  environment projection, `--cleanenv` by default, image/SIF refs, GPU access
  flags, and redacted metadata.
- The Apptainer/Singularity direct executor runs prepared stage attempts
  through the same worker/result pattern as subprocess and Docker.
- SLURM dry-run scripts and live submission can run resolved Apptainer
  execution commands while preserving existing manifests, generated scripts,
  `sbatch`, status, cancel, resource mapping, and failure behavior.
- Build failures are reported before dry-run rendering or live `sbatch`; batch
  scripts do not hide Docker or Apptainer build commands.
- Selected-executor preflight reports command availability, build target
  readiness, image/SIF/output presence, bind roots, writable paths, environment
  requirements, resource ownership, and scheduler/container compatibility with
  stable IDs.
- Feature docs and examples show build target reuse, SIF construction, direct
  Apptainer execution, SLURM composition, clean environment defaults, output
  refs, and explicit deferrals.
- Default imports, CLI help, preflight for unrelated executors, and
  `make validate-pr` do not require Docker, Apptainer, Singularity, SLURM,
  images, registries, fakeroot, or network access.

## Non-Goals

- No external or site build-service adapters.
- No Apptainer remote-build support assumption.
- No registry login/auth helpers, image publishing, image lock files, or
  global cross-run container cache.
- No automatic image conversion beyond explicit user-authored build sources
  accepted by the selected runtime.
- No per-stage recipe generation or domain-specific environment management.
- No Docker Compose, Kubernetes, cloud container orchestration, or container
  service lifecycle management.
- No whole-controller-in-container mode.
- No path translation protocol.
- No MPI rank orchestration, `mpirun`/`srun` policy, PMI/PMIx compatibility
  policy, or site module setup.
- No broad retry, timeout, transaction, event, cleanup, retention, or GC
  policy.
- No security-sandbox guarantee for untrusted project code.
- No real runtime, cluster, network, registry, or fakeroot requirement in
  default tests.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep `loom` domain-neutral, dependency-light, and optional-runtime friendly.
- Keep authored configs trusted project code, while redacting persisted command
  arguments, build args, environment values, provenance, diagnostics, and
  failure details.
- Keep shared `container_build` records import-light and executor-owned. They
  must not import Docker, Apptainer, SLURM, diagnostics presentation, CLI
  modules, plugin discovery, optional SDKs, or registry clients.
- Keep runtime-specific command runners adapter-local. Do not introduce a
  universal command-runner framework in Stage 18.
- Use structured argv records where Loom executes commands directly. Shell text
  belongs only in deterministic SLURM script rendering.
- Preserve current adapter namespace replacement semantics for
  `container_build`; do not invent per-target deep merge in this stage.
- Resolve local foreground builds before SLURM dry-run rendering or live
  submission.
- Keep SLURM as scheduler authority for nodes, tasks, CPU, memory, wall time,
  submitted-operation records, status, and cancellation.
- Keep Apptainer as container runtime authority for image/SIF, binds, workdir,
  clean env, explicit environment projection, and device flags such as `--nv`
  and `--rocm`.
- Keep default preflight cheap: no pulls, registry contacts, real runtime
  invocation, network checks, or fakeroot probes unless explicitly enabled.
- Every phase PR must run targeted validation, `make validate-pr`, and
  `make test-summary` unless a command is unavailable and the phase artifact
  records the reason.

## Design Principles

- Compose existing machinery. Stage 18 changes how a prepared attempt is
  invoked, not how Loom plans DAGs, commits outputs, or owns authority state.
- Build facts before execution. The selected image/SIF output ref should be
  resolved before direct execution or SLURM rendering depends on it.
- Shared contracts stay small. Generic build records cover target/source/
  policy/request/result/output refs; Docker and Apptainer command semantics
  remain adapter-specific.
- Fail closed on filesystem ambiguity. Host run directories and local artifact
  roots must be visible at the paths the worker metadata expects, or execution
  reports a clear diagnostic.
- Explicit environment handoff. Apptainer uses clean environment behavior by
  default and only projects configured variables or selected host variables.
- Scheduler and container roles stay separate. SLURM requests resources;
  Apptainer exposes runtime environment and devices; Loom does not own ranks.
- Evidence is not authority. Build evidence, generated scripts, logs, and
  metadata are inspectable facts, not lifecycle authority or committed stage
  outputs by default.
- Fake by default, smoke by opt-in. Default tests prove contracts and command
  construction without requiring site infrastructure.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Shared build namespace | Add separate `container_build` adapter namespace with whole-namespace replacement semantics | Avoids widening the Stage 17 `container` execution namespace and avoids hidden per-target merge policy |
| Build contract package | Add shared records under executor-owned container modules; prefer the planning-approved `loom.pipeline.executors.container` shape unless Stage 17 lands a compatible plural package to extend | Keeps build data import-light while avoiding duplicate shared container packages after Stage 17 lands |
| Build service | Implement local foreground build/reuse request-result protocol and fake implementation | Satisfies build-service behavior without daemon, remote build, registry, or site policy |
| Runtime builders | Keep Docker and Apptainer builders as adapters over shared build requests | Allows shared target selection and output refs without moving runtime command semantics into generic records |
| SIF construction | Support user-authored definition files and explicit local/URI sources accepted by `apptainer build` | Records useful build provenance while deferring auth helpers and automatic conversion |
| Build policy | Support `if_stale`, `always`, and `never` initially | Gives deterministic reuse/build/fail behavior without a global cache |
| Direct executor | Add CLI-backed Apptainer/Singularity executor that mirrors prepared-worker subprocess/Docker behavior | Preserves parent-owned finalization and worker result semantics |
| Runtime command choice | Treat `apptainer` as primary and `singularity` as compatible command/executor name with selected command identity recorded | Supports common HPC installs without divergent semantics |
| Environment | Use `--cleanenv` or equivalent clean behavior plus explicit projection by default | Reduces secret leakage and improves reproducibility |
| Resource ownership | SLURM owns allocation/enforcement in scheduler modes; Apptainer owns container/device flags | Avoids double-enforcement claims and rank orchestration creep |
| SLURM composition | Wrap existing generated worker or continuation argv in resolved `apptainer exec` commands | Reuses dry-run/live SLURM paths and keeps scripts inspectable |
| Build ordering | Resolve builds on submit/controller side before dry-run script rendering or `sbatch` | Keeps build failures distinct from scheduler/job failures |
| Preflight | Add stable selected-executor and selected-build-target checks with cheap defaults | Gives actionable readiness diagnostics without runtime/cluster requirements |
| Validation | Fake builders, fake command runners, deterministic scripts, and optional real smoke | Keeps CI reliable while preserving a path for site acceptance |

## Conflicts And Tradeoffs

- Stage 17 is expected but not landed in source. This plan can draft phases
  from confirmed Stage 18 planning, but Phase 1 execution planning must refresh
  and reconcile actual Stage 17 modules before code changes begin.
- `container_build` whole-namespace replacement is simpler and matches current
  adapter semantics, but it prevents ergonomic per-target overlays. The plan
  accepts this debt to avoid creating a hidden public merge model.
- A local foreground build service is less flexible than external/site build
  services, but it is testable, inspectable, and consistent with current
  Apptainer remote-build reality.
- Fake validation cannot prove site-specific Apptainer, SLURM, fakeroot,
  registry, or shared-filesystem behavior. The default gate proves Loom's
  contract shape; optional smoke covers real environments when available.
- Path parity is stricter than path translation, but it avoids corrupting
  persisted host paths, run URIs, artifact roots, and worker metadata.
- Keeping command runners adapter-local avoids premature abstraction, but it
  may create similar Docker and Apptainer runner code. Revisit only after
  duplicated behavior has a stable shared shape.

## Maintainability Assessment

The phase split keeps public contracts, build execution, direct container
execution, scheduler composition, and final diagnostics/docs separate. That is
important because Stage 18 touches multiple durable surfaces: runtime profiles,
executor descriptors, build records, worker invocation, SLURM scripts,
preflight, provenance, and feature docs. The plan avoids making a single phase
own both public build contracts and scheduler behavior.

The main maintainability risks are public config creep, runtime-specific fields
leaking into shared records, hidden SLURM build behavior, and one-off command
runner abstractions. Each phase has stop conditions around those risks.

## Extensibility Assessment

The plan leaves room for future Docker improvements, external/site builders,
image locks, stronger image identity policies, path translation, MPI support,
remote artifact-store integrations, Stage 19 reliability policy, Stage 20 event
projection, and Stage 21 cleanup. Those future features should consume shared
build/result/output facts and executor/scheduler metadata rather than parsing
logs or scripts.

The shared build contract is intentionally small: target, source, policy,
request, result, output ref, redacted command/provenance, and failure facts.
Future adapters can implement the same protocol without forcing core imports
of Docker, Apptainer, SLURM, registry clients, or cloud SDKs.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Stage 17 source was absent at draft time | Phase 1 source refresh found landed Stage 17 shared container and Docker modules present on `origin/develop`; the stale draft risk is resolved for implementation | A later rebase removes or materially changes `src/loom/pipeline/executors/containers.py` or Docker executor contracts |
| `container_build` uses whole-namespace replacement | Matches current adapter option merge behavior and avoids inventing typed target merging in Stage 18 | Users need per-target overlay, deletion, or profile composition semantics |
| No global build cache or image lock file | Stage 18 is local foreground build/reuse, not a registry or cache authority stage | External/site build services, image locks, or semantic image fingerprints are selected |
| Path parity only | Keeps run-store and artifact metadata simple and fail-closed | Remote stores, non-shared filesystems, or HPC layouts require explicit path mapping |
| Real runtime/cluster evidence optional | Default validation must be deterministic and not require site infrastructure | Release policy requires live Docker/Apptainer/SLURM acceptance |
| Adapter-local command runners may duplicate small helpers | Avoids premature universal command runner and keeps runtime semantics local | Docker and Apptainer implementations repeat substantial validated behavior |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by manager on 2026-05-17; no product-design blockers
- Refinement pass: complete; stale Stage 17 source evidence and gate metadata
  were refreshed before Phase 1 code changes
- Confirmation review: complete by manager on 2026-05-17; no remaining
  blockers
- Automatic merge mode: enabled after phase PRs pass automated review and
  validation
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Phased Implementation

### Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `container-build-contracts` | merged | `codex/container-build-contracts` | [#182](https://github.com/samcantrill/loom/pull/182) | Shared build records, config semantics, descriptor namespaces | Establish `container_build` contracts and whole-namespace replacement behavior | Package, unit, contract, profile/descriptor tests; `make validate-pr`; `make test-summary` | Named build-target config and namespace override |
| 2 | `local-container-builders` | merged | `codex/local-container-builders` | [#183](https://github.com/samcantrill/loom/pull/183) | Local build service, fake service, Docker/Apptainer build adapters | Build or reuse Docker image refs and Apptainer SIF refs through shared requests | Unit, contract, fake builder integration; `make validate-pr`; `make test-summary` | SIF build, build policy, output refs |
| 3 | `apptainer-executor` | merged | `codex/apptainer-executor` | [#184](https://github.com/samcantrill/loom/pull/184) | Apptainer/Singularity options, command builders, direct executor | Run prepared stage attempts through `apptainer exec`/`singularity exec` | Command-builder, descriptor, fake-runner executor tests; `make validate-pr`; `make test-summary` | Direct Apptainer stage execution |
| 4 | `slurm-apptainer-composition` | merged | `codex/slurm-apptainer-composition` | [#185](https://github.com/samcantrill/loom/pull/185) | SLURM argv wrapping, build-before-render/submission, live reuse | Compose existing SLURM dry-run/live paths with resolved Apptainer execution | Script rendering, manifest, fake `sbatch`/status/cancel integration; `make validate-pr`; `make test-summary` | SLURM plus Apptainer dry-run/live |
| 5 | `container-preflight-docs` | pr_open | `codex/container-preflight-docs` | [#186](https://github.com/samcantrill/loom/pull/186) | Preflight, docs, examples, optional smoke hooks | Finish selected diagnostics, docs, examples, and opt-in runtime smoke | Stable check-ID tests, docs examples, fake e2e where practical; `make validate-pr`; `make test-summary` | Preflight, docs, optional smoke |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Implementation-plan quality gate | Repository workflow | Manager review completed, stale Stage 17 evidence refined, and confirmation review recorded before Phase 1 code changes | resolved |
| Stage 17 source refresh before code | Planning accepted risk and source refresh | Phase 1 execution planning inspected landed Docker/shared-container source and selected `src/loom/pipeline/executors/containers.py` as the extension point | resolved |

## Phase 1: Shared Build Contracts And Config Semantics

Status: merged
Slug: `container-build-contracts`
Branch: `codex/container-build-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/container-build-contracts`
PR: https://github.com/samcantrill/loom/pull/182
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates reusable public
adapter contracts and must reconcile Stage 17 source

### Scope

- Goal: establish the shared Docker/Apptainer build contract before adding
  runtime build or execution behavior.
- Files/modules owned:
  - Stage 17 landed shared container modules, or new
    `src/loom/pipeline/executors/container/` if no compatible package exists
  - `src/loom/pipeline/runtime/capabilities.py`
  - `src/loom/pipeline/runtime/profiles.py` if explicit namespace validation
    tests expose needed changes
  - focused tests under `tests/unit/loom/pipeline/executors/`,
    `tests/unit/loom/pipeline/`, `tests/contracts/`, and `tests/package/`
- Behavior implemented:
  - Import-light records for build target, build source, build policy, build
    request, build result, build output ref, build key/fingerprint summary,
    redacted command projection, and failure diagnostics.
  - `container_build` adapter namespace contract with whole-namespace
    replacement semantics documented and tested.
  - Descriptor namespace claims for selected executors that need `container`,
    `container_build`, `docker`, `apptainer`, `singularity`, or `slurm`
    adapter options.
  - Serialization, unknown-field rejection, redaction, and plain-data
    validation for shared records.
- Decisions applied: DAQ-1, DAQ-2, DAQ-3, DAQ-7, DAQ-8, DAQ-11, DAQ-12.
- Examples or docs covered: minimal runtime/profile snippets for named build
  targets and complete namespace override behavior.
- Out of scope:
  - Running Docker or Apptainer commands.
  - Local build-service execution.
  - Direct Apptainer stage execution.
  - SLURM script composition.
  - Per-target deep merge, global cache, image locks, registry/auth helpers.
- Dependencies:
  - Stage 17 source refresh at phase start.
  - Existing runtime profile adapter option behavior.

### Tasks

- Refresh landed Stage 17 Docker/shared-container source and record the result
  in the phase execution plan before code changes.
- Choose the final shared package path by reusing landed Stage 17 modules when
  compatible; do not create duplicate singular/plural shared packages.
- Define schema-versioned shared build records and output refs for Docker image
  identities and Apptainer SIF paths.
- Add validation for build source kinds, explicit source paths/URIs, output ref
  kinds, policy names, build target names, and redaction-safe metadata.
- Add helpers for deterministic build-key summaries that do not fetch
  network-backed sources by default.
- Add tests for record round trips, redaction, output refs, `container_build`
  whole-namespace replacement, descriptor namespace claims, and import
  boundaries.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors tests/unit/loom/pipeline/test_runtime_profiles.py tests/unit/loom/pipeline/test_executor_capabilities.py tests/contracts/test_runtime_profiles_contract.py tests/contracts/test_executor_capabilities_contract.py tests/package` | Target shared build records, profile semantics, descriptor claims, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: shared records validate, serialize, redact, and reject
  invalid target/source/policy/output combinations.
- Design-decision evidence: `container_build` is separate from `container` and
  uses whole-namespace replacement semantics.
- Future-roadmap compatibility evidence: build facts are generic enough for
  Stage 19-21 without runtime command imports.
- Interface, adapter, or protocol reuse evidence: output refs and build
  request/result records are runtime-neutral and adapter-extensible.
- Documentation evidence: examples show named build targets and override
  semantics.
- Domain-neutrality evidence: records do not encode package, OS, dataset,
  model, or site-specific environment choices.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: expanded path; draft and refine completed because
  this phase created public adapter contracts
- Implementation/refinement budget: not needed; local and CI validation passed
- PR review budget: completed by manager before merge
- Blocker-resolution budget: 1/3 used for the post-review
  serialization/redaction fix
- Pre-submit blocker gate: passed; implementation-plan quality gate complete
- Merge record: merged to `develop` in
  `aa8cf48a015edfec0a67130876227ae69683f900`

### Risks And Stop Conditions

- Risks: Stage 17 incompatibility, duplicate shared package paths, public merge
  semantics confusion, Docker/Apptainer leakage into shared records, or raw
  adapter payload persistence.
- Stop conditions:
  - Stage 17 source becomes absent again after rebase and the manager has not
    explicitly authorized proceeding with prerequisite shared container work.
  - Landed Stage 17 contracts materially contradict the confirmed planning
    guardrails.
  - Shared records require Docker or Apptainer imports.
- Assumptions: current adapter namespace replacement semantics remain the
  correct public behavior for Stage 18.

### Completion Summary

- Implementation: added schema-versioned shared `container_build` records,
  Docker/Apptainer output refs, build policies, deterministic build-key
  summaries, redacted command/evidence/failure records, descriptor namespace
  claims, and focused unit/contract/profile/package coverage.
- Validation: targeted Phase 1 suite passed with 172 passed, 1 skipped;
  post-review focused suite passed with 16 passed; `make validate-pr` passed;
  `make test-summary` passed with 2293 passed, 18 skipped, 1871 deselected;
  GitHub CI `checks` passed on PR #182.
- PR: https://github.com/samcantrill/loom/pull/182
- Merge: merged to `develop` as
  `aa8cf48a015edfec0a67130876227ae69683f900`
- Follow-up: Phase 2 starts from updated `develop`; no successor branch was
  active at merge time, so the Phase 1 branch/worktree can be cleaned.

## Phase 2: Local Build Service And Runtime Builders

Status: merged
Slug: `local-container-builders`
Branch: `codex/local-container-builders`
Worktree: `/home/samcantrill/work/loom-worktrees/local-container-builders`
PR: https://github.com/samcantrill/loom/pull/183
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase adds build request/result
protocols and runtime-specific command semantics

### Scope

- Goal: implement foreground/local build and reuse behavior for Docker image
  refs and Apptainer SIF refs through the shared build contract.
- Files/modules owned:
  - shared build-service protocol and fake implementation under the selected
    container build package
  - Docker build adapter module under landed Docker package or a new
    Docker-specific builder module
  - Apptainer build adapter module under `src/loom/pipeline/executors/apptainer/`
  - build evidence serialization helpers and focused tests
- Behavior implemented:
  - Local build-service request/result protocol with fake implementation.
  - Build policy evaluation for `if_stale`, `always`, and `never`.
  - Output validation and reuse/fail/build decisions.
  - Docker build command construction compatible with the shared request shape.
  - Apptainer `build` argv construction for definition files and explicit
    local/URI sources accepted by Apptainer.
  - Redacted build command metadata, output refs, log references, and failure
    diagnostics.
- Decisions applied: DAQ-3, DAQ-7, DAQ-8, DAQ-9, DAQ-11, DAQ-12.
- Examples or docs covered: SIF build, local build service, shared
  build-and-run target, build output/evidence separation.
- Out of scope:
  - External/site build services, daemon queues, registry login/auth helpers,
    publishing, global image cache, image lock files, automatic conversion.
  - Direct Apptainer stage execution.
  - SLURM composition.
- Dependencies: Phase 1 shared build records and namespace semantics.

### Tasks

- Add local builder protocol and fake builder/service implementation.
- Add deterministic build policy evaluator and output existence/staleness
  checks that avoid network-backed source fetches by default.
- Add Docker builder adapter over shared requests, using CLI/buildx-compatible
  argv records without adding Docker SDK dependency.
- Add Apptainer SIF builder adapter with options for definition file/source,
  output path, fakeroot/notest/force/sandbox-style selections where supported
  by confirmed config.
- Add redaction and bounded log/evidence metadata for build success, reuse, and
  failure.
- Add tests for fake build success/reuse/failure, policy decisions, invalid
  targets, output validation, command projection, and redaction.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors tests/integration/pipeline tests/contracts` | Target build policy, fake service, runtime builder adapters, and integration with run-local evidence | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: fake builders deterministically build, reuse, fail, and
  validate Docker and Apptainer outputs.
- Design-decision evidence: build evidence is run-local while output refs are
  explicit adapter outputs.
- Future-roadmap compatibility evidence: external/site builders can implement
  the same request/result protocol later.
- Interface, adapter, or protocol reuse evidence: Docker and Apptainer builders
  consume shared requests without sharing command-runner implementations.
- Documentation evidence: snippets show SIF build and build output refs.
- Domain-neutrality evidence: Loom records sources and commands but does not
  generate project-specific Dockerfiles or Apptainer definitions.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: expanded path; draft and refine completed
- Implementation/refinement budget: not needed; local and full validation passed
- PR review budget: completed by manager before merge
- Blocker-resolution budget: 1/3 used for structured builder launch-failure
  results after manager review
- Pre-submit blocker gate: Phase 1 merged or valid stack predecessor recorded
- Merge record: merged to `develop` in
  `a3f62c246a6505915c8c631d41bb1da2710ff129`

### Risks And Stop Conditions

- Risks: build service becoming a daemon/registry abstraction, implicit network
  probes, raw env/build args in metadata, or accidental image conversion
  policy.
- Stop conditions:
  - Build policy requires global cache or image lock semantics.
  - Apptainer build behavior needs site/fakeroot assumptions that cannot be
    represented as explicit diagnostics.
  - Docker builder compatibility requires changing Docker execution contracts
    from Stage 17.
- Assumptions: foreground local build is sufficient for Stage 18.

### Completion Summary

- Implementation: complete; added shared local build policy/service/fake
  builder behavior, Docker build adapters over the existing runner, and a
  build-only Apptainer SIF builder package.
- Validation: focused Phase 2 suite passed with 133 passed, 1 skipped;
  phase-level targeted suite passed with 519 passed, 7 skipped; `make
  validate-pr` passed; `make test-summary` passed with 2308 passed, 18
  skipped, 1886 deselected; post-review focused adapter suite passed with 11
  passed, and full validation was rerun after the review fix.
- PR: https://github.com/samcantrill/loom/pull/183
- Merge: merged to `develop` as
  `a3f62c246a6505915c8c631d41bb1da2710ff129`
- Follow-up: Phase 3 starts from updated `develop`; no successor branch was
  active at merge time, so the Phase 2 branch/worktree can be cleaned.

## Phase 3: Direct Apptainer And Singularity Execution

Status: merged
Slug: `apptainer-executor`
Branch: `codex/apptainer-executor`
Worktree: `/home/samcantrill/work/loom-worktrees/apptainer-executor`
PR: https://github.com/samcantrill/loom/pull/184
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase adds a new executor and public
runtime behavior

### Scope

- Goal: run prepared stage attempts through Apptainer/Singularity using the
  normal worker/result contract.
- Files/modules owned:
  - `src/loom/pipeline/executors/apptainer/`
  - executor registration/selection paths consistent with existing local,
    subprocess, Docker, and SLURM patterns
  - `src/loom/pipeline/runtime/capabilities.py`
  - focused unit, contract, and integration tests
- Behavior implemented:
  - Apptainer/Singularity options and validation.
  - Command availability/version probes with fakeable command runner.
  - Deterministic `apptainer exec`/`singularity exec` argv construction.
  - Bind mounts, workdir, path-parity validation, selected environment
    projection, clean-env default, image/SIF ref handling, GPU flags, and
    redacted metadata.
  - `ApptainerExecutor` result handling for launch failures, process failures,
    worker-result failures, missing/invalid worker results, and
    process/worker conflicts.
- Decisions applied: DAQ-1, DAQ-4, DAQ-6, DAQ-10, DAQ-11, DAQ-12.
- Examples or docs covered: direct Apptainer stage execution and clean
  environment behavior.
- Out of scope:
  - SLURM script composition and live submission.
  - Whole-controller-in-container mode.
  - In-process stage execution inside the container.
  - MPI/rank orchestration, path translation, site modules, or security
    sandbox claims.
- Dependencies: Phase 1 shared records and Phase 2 resolved output refs.

### Tasks

- Add Apptainer/Singularity command option records and command builder.
- Add adapter-local command runner protocol and bounded result records.
- Add runtime descriptors for `apptainer` and `singularity`, including adapter
  namespace claims and precise resource capability language.
- Add direct executor that mirrors subprocess/Docker prepared-worker result
  handling and records selected command identity.
- Add metadata helpers for runtime version, image/SIF identity, bind summaries,
  environment key summaries, GPU flags, exit/signal facts, and log paths.
- Add tests for argv construction, redaction, env projection, bind validation,
  GPU flags, runtime alias behavior, and fake-runner success/failure flows.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors tests/unit/loom/pipeline/test_executor_capabilities.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/contracts/test_executor_contract.py tests/package` | Target command construction, descriptors, import boundaries, and prepared-worker result parity | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: fake direct execution returns normal
  `StageExecutionResult` values for success, worker failure, process failure,
  launch failure, and conflict cases.
- Design-decision evidence: `apptainer` is primary, `singularity` compatibility
  records selected command identity, and clean environment is default.
- Future-roadmap compatibility evidence: Stage 19 can consume generic
  process/runtime/container facts.
- Interface, adapter, or protocol reuse evidence: command runner remains
  Apptainer-local and shared records are not polluted with Apptainer flags.
- Documentation evidence: direct execution example aligns with command-builder
  tests.
- Domain-neutrality evidence: executor only invokes configured stage workers;
  it does not generate project environment content.

### Phase Workflow State

- Phase execution plan: completed and merged with PR #184
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: no phase refiner pass used
- PR review budget: manager automated review used; final target/check
  verification passed before merge
- Blocker-resolution budget: 1/3 used for required host environment projection
- Pre-submit blocker gate: Phase 2 merged or valid stack predecessor recorded
- Merge record: merged to `develop` on 2026-05-17 as squash commit `99df16c`

### Risks And Stop Conditions

- Risks: host environment leakage, raw secrets in metadata, path-parity
  ambiguity, overpromised resource enforcement, or divergent Singularity
  behavior.
- Stop conditions:
  - Direct execution requires path translation.
  - A real runtime requirement appears in default tests.
  - Environment projection cannot be kept redaction-safe.
- Assumptions: Apptainer/Singularity execution can follow the existing
  prepared-worker pattern.

### Completion Summary

- Implementation: direct Apptainer/Singularity command construction,
  fake/subprocess exec runners, prepared-worker executor integration,
  CLI/top-level executor selection, selected-command metadata, redaction-safe
  environment projection, path-parity bind injection, and fake-runner
  integration coverage are implemented in `codex/apptainer-executor`.
- Validation: `make validate-pr` passed outside the sandbox; `make
  test-summary` passed with overall 2334 passed, 18 skipped, 1912 deselected.
- Review fix: manager review found and fixed Apptainer required host
  environment projection so selected host variables are passed as redacted
  `--env NAME=value` entries rather than Docker-style name-only entries.
- GitHub CI: PR #184 `checks` passed on the updated head before merge.
- PR: https://github.com/samcantrill/loom/pull/184 merged into `develop`
- Merge: squash commit `99df16c`
- Follow-up: SLURM wrapping, selected preflight, docs/examples, and optional
  real runtime smoke remain Phase 4 and Phase 5 work.

## Phase 4: SLURM Plus Apptainer Composition

Status: merged
Slug: `slurm-apptainer-composition`
Branch: `codex/slurm-apptainer-composition`
Worktree: `/home/samcantrill/work/loom-worktrees/slurm-apptainer-composition`
PR: https://github.com/samcantrill/loom/pull/185
Merge commit: `4c7110a21af20070ea4fef305d55116ed9aaa376`
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase composes scheduler and
container behavior across dry-run and live submission paths

### Scope

- Goal: compose existing SLURM dry-run/live submission machinery with resolved
  Apptainer execution.
- Files/modules owned:
  - `src/loom/pipeline/executors/slurm/` composition points
  - Apptainer command wrapping helpers where they are adapter-owned
  - build-before-render/submission integration points
  - focused SLURM unit, contract, integration, and e2e tests with fake runners
- Behavior implemented:
  - Structured argv wrapping so generated SLURM worker or continuation commands
    run through `apptainer exec` against resolved SIF/image refs.
  - Submit-side/controller-side build resolution before dry-run rendering and
    before live `sbatch`.
  - Deterministic dry-run scripts with visible Apptainer execution commands and
    no hidden Docker or Apptainer build commands.
  - Live fake submission reuse of existing `sbatch`, submitted-operation
    manifest, status, cancel, scheduler status, and failure records.
  - Resource ownership summaries that distinguish SLURM allocation from
    Apptainer runtime/device flags.
- Decisions applied: DAQ-5, DAQ-6, DAQ-8, DAQ-10, DAQ-11, DAQ-12.
- Examples or docs covered: SLURM plus Apptainer dry-run, live SLURM plus
  Apptainer, submit-side build before rendering/submission.
- Out of scope:
  - New `slurm-apptainer` executor names.
  - New scheduler implementation.
  - Build commands inside batch scripts.
  - Site module policy.
  - MPI rank policy or multi-node topology decisions.
- Dependencies: Phase 2 build outputs and Phase 3 Apptainer command builder.

### Tasks

- Add a minimal SLURM command composition hook that wraps an existing
  `SlurmCommandArgv` with resolved Apptainer execution.
- Thread resolved build output refs into dry-run planning and live submission
  without changing SLURM authority ownership.
- Ensure dry-run artifacts and manifests record safe summaries of container
  execution while preserving existing generated paths.
- Ensure live submission performs build resolution before invoking `sbatch` and
  maps build failures to controller-side failures.
- Add tests for single-job and afterok script rendering, manifest summaries,
  build-before-render ordering, build-before-submit ordering, fake `sbatch`,
  status, cancel, and existing SLURM regressions.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_dry_run_planning.py tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/e2e/test_cli_slurm_dry_run.py tests/e2e/test_cli_slurm_live_single_job.py tests/e2e/test_cli_slurm_live_afterok.py` | Target deterministic scripts, manifests, live fake submission, and existing SLURM regressions | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: generated scripts contain Apptainer-wrapped worker
  commands against resolved outputs and contain no build commands.
- Design-decision evidence: SLURM remains scheduler authority and build
  failures occur before submission.
- Future-roadmap compatibility evidence: Stage 19 can distinguish build,
  launch, scheduler, and worker failures.
- Interface, adapter, or protocol reuse evidence: composition is argv/script
  wrapping, not a new scheduler backend.
- Documentation evidence: script snippet aligns with rendering tests.
- Domain-neutrality evidence: no site module, MPI rank, or topology policy is
  encoded.

### Phase Workflow State

- Phase execution plan: completed in
  `docs/roadmap/stage-18/phases/slurm-apptainer-composition.md`
- Planning/refinement budget: expanded path; draft and refine completed
- Implementation/refinement budget: one `loom_phase_refiner` pass available if
  scheduler/container boundaries or validation fail
- PR review budget: used by manager automated review; final target/check
  verification passed before merge
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phase 3 merged or valid stack predecessor recorded
- Merge record: PR #185 merged to `develop` as
  `4c7110a21af20070ea4fef305d55116ed9aaa376`

### Risks And Stop Conditions

- Risks: hidden batch-script builds, broken submitted-operation manifests,
  duplicated scheduler implementation, resource double-enforcement claims, or
  accidental rank orchestration.
- Stop conditions:
  - SLURM wrapping requires a new scheduler executor instead of composing
    existing dry-run/live paths.
  - Build resolution cannot be kept before rendering/submission.
  - Existing SLURM status/cancel semantics regress.
- Assumptions: existing `SlurmCommandArgv` and rendering paths are sufficient
  composition points.

### Completion Summary

- Implementation: added SLURM/Apptainer command composition helpers,
  `SlurmCommandArgv` metadata, run-level and stage-level container wrapping,
  selected Apptainer SIF target resolution before dry-run rendering/live
  submission, redacted container command/build metadata, and focused
  unit/contract/integration/e2e coverage in
  `codex/slurm-apptainer-composition`.
- Validation: targeted SLURM/CLI unit suite passed with 103 passed; targeted
  contract/integration/e2e suite passed with 21 passed and 3 skipped;
  `make validate-pr` passed outside the sandbox; `make test-summary` passed
  with overall 2344 passed, 18 skipped, 1922 deselected.
- PR: https://github.com/samcantrill/loom/pull/185 opened against `develop`;
  body drafted in
  `docs/roadmap/stage-18/phases/slurm-apptainer-composition-pr-body.md`;
  GitHub `checks` passed before merge.
- Merge: PR #185 merged into `develop` as squash commit
  `4c7110a21af20070ea4fef305d55116ed9aaa376`.
- Follow-up: selected-executor preflight, user docs/examples, and optional
  real runtime/cluster smoke remain Phase 5 work.

## Phase 5: Preflight, Docs, And Opt-In Runtime Smoke

Status: pr_open
Slug: `container-preflight-docs`
Branch: `codex/container-preflight-docs`
Worktree: `/home/samcantrill/work/loom-worktrees/container-preflight-docs`
PR: https://github.com/samcantrill/loom/pull/186
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase finalizes user-facing
diagnostics, docs, examples, and validation evidence across prior phases

### Scope

- Goal: finish selected-executor diagnostics, user-facing docs, examples, and
  optional real runtime/cluster smoke hooks.
- Files/modules owned:
  - `src/loom/diagnostics/models.py`
  - `src/loom/diagnostics/preflight.py`
  - `src/loom/cli/preflight.py` if presentation updates are needed
  - `docs/features/container-executors.md`
  - `docs/features/slurm.md`
  - `docs/features/preflight.md`
  - `docs/features/provenance.md`
  - `docs/features/testing.md`
  - focused unit, contract, integration, e2e, and optional smoke tests
- Behavior implemented:
  - Stable preflight check IDs for build targets, runtime command
    availability, build readiness, image/SIF/output presence, bind roots,
    writable paths, environment requirements, resource mapping, and
    scheduler/container compatibility.
  - JSON-safe diagnostic details with redacted metadata and selected namespace
    behavior.
  - Docs and examples for named build targets, local build service, SIF build,
    direct Apptainer execution, SLURM composition, clean-env defaults, output
    refs, and deferrals.
  - Marked/manual opt-in smoke hooks for real Docker, Apptainer/Singularity,
    SIF build, and SLURM when available.
- Decisions applied: DAQ-7, DAQ-8, DAQ-9, DAQ-10, DAQ-11, DAQ-12.
- Examples or docs covered: all confirmed examples from the planning artifact.
- Out of scope:
  - Requiring real runtimes, clusters, registries, fakeroot, or network in
    default validation.
  - Registry/auth helpers, image publishing, external build services, cleanup
    policy.
- Dependencies: Phases 1-4.

### Tasks

- Add stable preflight IDs and selected-executor/build-target checks.
- Add cheap pass/fail/skip diagnostics for missing commands, missing images or
  outputs, invalid build targets, invalid binds, unwritable paths, missing env
  variables, unsupported resources, and scheduler/container mismatch.
- Update feature docs and examples to match implemented config/schema names and
  command/script output.
- Add optional marked or manual smoke hooks that are skipped unless explicitly
  enabled.
- Run final cross-phase validation and update implementation-plan evidence as
  phase work completes.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/diagnostics tests/contracts/test_diagnostics_preflight_contract.py tests/integration/diagnostics tests/e2e/test_cli_slurm_dry_run.py tests/package` | Target stable diagnostics, JSON output, selected namespace behavior, script/doc integration, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |
| Optional marked/manual real Docker/Apptainer/SIF/SLURM smoke | Site/runtime acceptance outside default CI | no |

### Acceptance Evidence

- Behavior evidence: preflight reports stable cheap diagnostics for selected
  build/direct/SLURM paths.
- Design-decision evidence: default checks do not perform network, runtime, or
  fakeroot probes.
- Future-roadmap compatibility evidence: diagnostic IDs and failure categories
  are stable enough for Stage 19 reliability policy.
- Interface, adapter, or protocol reuse evidence: diagnostics consume safe
  summaries from build/executor/scheduler adapters.
- Documentation evidence: feature docs show all confirmed examples and
  deferrals.
- Domain-neutrality evidence: examples use generic project/container names and
  avoid domain-specific dependency management.

### Phase Workflow State

- Phase execution plan: completed in
  `docs/roadmap/stage-18/phases/container-preflight-docs.md`
- Planning/refinement budget: expanded path; draft and refine expected because
  this phase verifies cross-cutting user-facing behavior
- Implementation/refinement budget: not needed; targeted and full validation
  passed without a refinement pass
- PR review budget: one automated review pass pending
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phase 4 merged or valid stack predecessor recorded
- Merge record: pending GitHub checks, automated review, and merge

### Risks And Stop Conditions

- Risks: check-ID churn, default runtime/network dependency, docs drifting from
  implemented schema, or optional smoke becoming mandatory.
- Stop conditions:
  - Preflight cannot stay cheap by default.
  - Docs require behavior not implemented in earlier phases.
  - Stable check IDs conflict with existing diagnostics conventions.
- Assumptions: final implemented schema names may differ from planning
  examples, but documented behavior must match the confirmed planning artifact.

### Completion Summary

- Implementation: selected-executor preflight now covers container build
  targets, direct Apptainer/Singularity command/options/image/environment,
  SLURM plus Apptainer compatibility, resource mapping, filesystem/path parity,
  and redacted JSON-safe details. Feature docs and skipped-by-default real
  runtime acceptance hooks were added.
- Validation: optional container acceptance hooks passed with 3 skipped;
  targeted diagnostics/package/e2e suite passed with 217 passed; Ruff and
  Pyright passed; `make validate-pr` passed; `make test-summary` passed with
  overall 2350 passed, 21 skipped, 1928 deselected.
- PR: https://github.com/samcantrill/loom/pull/186 opened against `develop`
- Merge: pending
- Follow-up: direct Apptainer/Singularity preflight intentionally does not
  resolve `container.target`; users should pass built SIF paths through
  `container.image.reference` until a future explicit target-resolution
  contract is approved.

## Cross-Phase Validation

- Full relevant test command: `make validate-pr`
- Suite evidence command: `make test-summary`
- Targeted package checks: import-boundary and CLI help tests for unrelated
  executors must show no Docker, Apptainer, Singularity, SLURM, image,
  registry, fakeroot, or network requirement.
- Targeted unit checks: shared build record validation, build policy,
  redaction, Apptainer build/exec argv, runtime descriptors, SLURM wrapping,
  and diagnostics.
- Targeted contract checks: runtime profile namespace semantics, executor
  capability/namespace claims, preflight stable IDs, and SLURM manifest/script
  shape.
- Targeted integration/e2e checks: fake build service, fake direct Apptainer
  execution, fake SLURM dry-run/live composition, CLI preflight, and docs
  examples where repository patterns support them.
- Docs/template checks: feature docs must show named build targets, SIF build,
  direct Apptainer execution, SLURM composition, clean-env defaults, output
  refs, validation defaults, and deferrals.
- Domain-neutrality checks: no package recipe generation, project-specific
  dependency management, site module policy, MPI rank policy, or security
  sandbox language.
- Example/demo checks: confirmed examples from planning must map to at least
  one default fake test or docs snippet, with real runtime smoke marked
  optional.
- Manual review focus: Stage 17 contract reconciliation, public config shape,
  redaction, build/output placement, SLURM authority preservation, path parity,
  and Stage 19 reliability compatibility.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| None | N/A | Manager plan review found no blocking plan-quality issues after planning readiness, design-safety evidence, future-roadmap compatibility, reusable interface assumptions, phase boundaries, and suite obligations were checked. | resolved |
| Stale Stage 17 source evidence | concern | Refined the plan to record landed Stage 17 source on `origin/develop` and to reuse `src/loom/pipeline/executors/containers.py` rather than creating a duplicate shared package. | resolved |

Gate result:

- Status: passed
- Review evidence:
  - Manager review on 2026-05-17 found no unresolved planning blockers,
    no unresolved `needs discussion` decisions, and no missing validation or
    phase-shaping obligations.
  - One bounded refinement updated stale Stage 17 source evidence and gate
    metadata after `origin/develop` was found to contain Stage 17 PRs #171
    through #175.
  - Manager confirmation on 2026-05-17 verified Phase 1 can proceed by
    extending the landed `loom.pipeline.executors.containers` module and
    Docker contracts.
- Accepted risks:
  - Real runtime/cluster validation remains optional by default.
  - `container_build` whole-namespace replacement and no global cache are
    accepted Stage 18 debts.
  - Stage 17 contract drift after later rebase remains a revisit trigger.
- Revisit triggers:
  - Stage 17 lands incompatible shared container or Docker contracts.
  - Phase work requires per-target merge semantics, path translation, registry
    auth, external build service, hidden SLURM builds, or MPI/rank policy.
  - Stage 19 reliability implementation requires facts not captured by Stage
    18 build/execution/scheduler records.

## Final Approval

- Approval status: approved for phase execution planning.
- Approved scope: Phase 1 through Phase 5 as recorded in this implementation
  plan, with each phase requiring a scope-complete phase execution plan before
  implementation.
- Accepted risks: real runtime/cluster validation remains optional by default,
  `container_build` whole-namespace replacement, no global build cache, and
  Stage 17 contract drift only if a later rebase materially changes the landed
  shared container/Docker contracts.
- Deferred items: external/site build services, registry/auth helpers,
  automatic conversion, global cache/image locks, Docker Compose, Kubernetes,
  image publishing, whole-controller-in-container mode, path translation,
  MPI/rank orchestration, site module policy, broad reliability policy, cleanup
  policy, and mandatory real runtime/cluster validation.
