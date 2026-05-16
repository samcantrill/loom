# Roadmap Stage 17 Implementation Plan: Docker Container Executor

Status: ready for phase implementation
Roadmap stage: `v17`
Planning document: `docs/roadmap/stage-17/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 5 pending
Blockers:

- None. Implementation-plan quality gate passed on 2026-05-16 after
  `loom_plan_reviewer` review found no blockers and manager confirmation
  verified no refinement was required.

## Summary

- Goal: implement a Docker CLI-backed executor that runs prepared stage
  attempts inside Docker containers while preserving Loom's existing
  stage-worker, run-store, artifact-store, diagnostics, log, and failure
  semantics.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-17/planning.md` with FR-1 through FR-10 closed.
- Approved behavior: `loom run CONFIG --executor docker` runs normal Loom
  pipelines whose selected stage attempts execute in Docker containers; the
  controller remains outside Docker; Docker failures are inspectable through
  existing status, log, failure, and diagnostics surfaces; Docker preflight is
  cheap by default; examples cover stage and pipeline Docker workflows.
- Source behavior confirmation: complete on 2026-05-16.
- Key design constraints: Docker CLI only, no Docker SDK, no default daemon or
  registry dependency in tests or preflight, path-parity mounts for run
  directories and local artifact roots, explicit environment handoff, redacted
  persisted metadata, no security-sandbox claim, and no whole-controller
  container mode.
- Source design-agreement gate: confirmed DAQ-1 through DAQ-12. Shared
  container records live under executor ownership, Docker-specific behavior
  lives under the Docker executor, `container` and `docker` adapter namespaces
  are distinct, and Docker reuses the prepared-worker lifecycle.
- Future-roadmap impact: Stage 18 can reuse shared container records,
  path-safety helpers, redaction rules, provenance conventions, preflight
  patterns, and fake-command tests for Apptainer/Singularity and
  SLURM-container composition. Stage 19 can wrap Docker failure/process facts
  with shared retry, timeout, failure-category, and transaction policy. Stage
  20 can project committed Docker/container facts into runtime events and
  observe-only event sinks. Stage 21 and later cleanup work can consume
  log/staging/materialization facts without changing artifact authority.
- Reusable interface, adapter, or protocol assumptions: shared container
  records are import-light plain-data value objects limited to image, workdir,
  mounts, explicit environment handoff, and resource intent; `DockerCommandRunner`
  is a narrow Docker-local protocol; executor descriptors claim adapter
  namespaces and resource capabilities without importing Docker behavior.
- Examples covered: direct/prepared stage Docker execution, normal
  `loom run --executor docker` pipeline execution, Docker preflight,
  inspectable Docker failure, runtime/profile configuration snippets, and
  optional real Docker smoke guidance.
- Source phase shaping: five phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-16.
- Out of scope: image build commands, registry authentication helpers,
  automatic image pulls, Compose, Kubernetes, Apptainer/Singularity,
  SLURM-container composition, advanced GPU mapping, whole-controller
  container mode, Docker as a security sandbox, broad retry/timeout policy,
  and default real Docker validation.

## Goal

Stage 17 adds Loom's first container executor. The Docker executor should make
containerized local and CI execution available without changing the core stage
contract: Loom still prepares one stage attempt, records durable worker
request data, runs the stage-worker command, reads the worker result, and lets
the parent runner finalize outputs, statuses, artifact indexes, logs, and
failures.

The implementation must make Docker useful and inspectable without making
Docker a required dependency for ordinary package use. Default tests and cheap
preflight paths must be daemon-free and network-free. Real Docker acceptance
can exist only as an explicit opt-in.

## Context

Stage 17 builds on existing Loom execution and artifact foundations:

- Stage 5 created the durable stage-worker path and subprocess executor. The
  Docker executor should mirror the prepared-worker pattern rather than
  creating a new runner mode.
- Stage 7 established fakeable backend command-runner patterns in SLURM live
  operations.
- Stage 15 added artifact-store records, backend contracts, immutable lookup,
  bundle ref semantics, and metadata-only external artifact behavior.
- Stage 16 added explicit materialization/staging operation evidence that
  container and HPC stages can use when local host-visible payload placement is
  needed.
- Current runtime profiles normalize adapter options and support per-stage
  adapter options. Stage 17 uses those existing namespace mechanics for
  `container` and `docker`.
- Current preflight already has selected-executor, resource, filesystem,
  artifact backend, subprocess, and SLURM checks. Docker extends this pattern
  with stable cheap check IDs.

The completed planning artifact records the user-approved interpretation of
pipeline examples: they are normal Loom pipeline runs whose selected stage
attempts execute through Docker, not a whole-controller-in-container mode.

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-17/planning.md`
- Functionality and behavior baseline: complete. The notes lock per-stage
  Docker execution, Docker CLI command construction, shared container records,
  runtime/profile adapter-owned configuration, path-parity mounts, explicit
  environment handoff, redacted metadata, provenance, Docker failures/logs,
  cheap preflight, fake-command validation, and examples.
- Design-safety review: passed on 2026-05-16 with no blockers. The review
  upheld the narrow shared `container` namespace, fail-closed path parity,
  strict redaction, precise resource capability language, cheap preflight and
  provenance defaults, and executor-level fake-command validation.
- Examples and validation strategy: complete. Examples and tests are
  daemon-free by default, with optional live Docker acceptance outside
  `make validate-pr`.
- Phase shaping: complete. Five reviewable phases are recorded below.
- Implementation readiness blockers from planning: none.
- Remaining workflow blocker: none; implementation-plan quality gate passed on
  2026-05-16.
- Accepted risks and revisit triggers:
  - Path-parity mounts only. Revisit when Stage 18, remote stores, or
    non-local authority backends require explicit host/container path
    translation.
  - GPU mapping unsupported in Stage 17. Revisit when a future stage selects a
    concrete GPU policy.
  - Docker digest metadata is best-effort. Revisit for image lock files,
    image-as-semantic-input policy, or stronger release acceptance.
  - Default validation uses fake Docker commands. Revisit if maintainers
    require live Docker evidence before release.
  - The public `container` namespace is intentionally narrow. Revisit if Stage
    18 needs incompatible generic fields or repeated Docker-specific
    exceptions appear in shared records.

## Desired Outcome

When all phases are complete:

- `loom.pipeline.executors.containers` provides import-light shared container
  records and helpers for image references, workdir, mounts, environment
  handoff, resource intent, path-parity validation, and redacted metadata
  projection.
- `loom.pipeline.executors.docker` provides Docker options, deterministic
  `docker run` command construction, a fakeable command-runner protocol,
  subprocess-backed runner, process-result mapping, metadata helpers, and
  `DockerExecutor`.
- Runtime descriptors and profiles can represent a selected Docker executor
  with shared `container` adapter options and Docker-specific `docker` options
  without adding Docker fields to semantic pipeline stage specs.
- `loom run CONFIG --executor docker` runs selected stage attempts through
  Docker using the prepared stage-worker command and normal parent-owned
  finalization.
- Docker failures, worker-result conflicts, log paths, exit codes, process
  facts, and redacted command metadata are inspectable through existing Loom
  surfaces.
- Docker selected-executor preflight reports cheap command, config, mount,
  run-directory, artifact-root, environment, and resource diagnostics with
  stable check IDs.
- Documentation and examples show both stage and pipeline Docker workflows,
  including preflight and failure inspection.
- Default package imports, CLI help, preflight for non-Docker executors,
  `make validate-pr`, and default examples do not require Docker, network,
  image pulls, registries, or the Docker Python SDK.

## Non-Goals

- No image build commands, image lock files, or image publishing flow.
- No registry authentication helper, automatic image pull, or default registry
  probe.
- No Docker Compose, Kubernetes, cloud container orchestration, or container
  service lifecycle management.
- No Apptainer/Singularity or SLURM-container composition implementation.
- No whole-controller-in-container mode.
- No advanced GPU mapping.
- No Docker SDK or provider SDK dependency.
- No security-sandbox guarantee for untrusted project code.
- No shared retry, timeout, event, transaction, or cleanup policy beyond
  recording executor facts that later stages can consume.
- No real Docker daemon requirement in default tests or `make validate-pr`.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep `loom` domain-neutral and dependency-light.
- Keep authored configs trusted, but keep persisted metadata redacted and
  shareable.
- Keep lifecycle ownership in `PipelineRunner`; Docker executor returns
  `StageExecutionResult` and must not own DAG semantics, resume policy,
  artifact indexes, final status authority, or cleanup.
- Keep shared container records under executor ownership and import-light. They
  must not import Docker behavior, CLI presentation, diagnostics presentation,
  plugin discovery, optional SDKs, run catalog, or daemon-facing code.
- Keep Docker-specific flags and command construction under Docker-specific
  modules.
- Use argv lists, not shell command strings.
- Require path-parity mounts for run directories and local artifact roots.
  Non-local, non-mountable, or mismatched path requirements fail closed with
  explicit diagnostics.
- Pass only explicit environment variables or selected required host names.
  Persist selected key summaries and redacted values only where needed for
  diagnosis.
- Do not persist raw adapter payloads or raw environment values in
  `runtime.json`, executor metadata, command metadata, failure records,
  provenance, or diagnostics.
- Keep default preflight cheap: no image pulls, registry contacts, daemon-heavy
  image probes, or network checks.

## Design Principles

- Preserve the stage contract. Docker changes how one prepared attempt is
  invoked, not what a stage means or how outputs are committed.
- Adapter-owned configuration. Container and Docker choices belong in
  runtime/profile adapter options, not semantic pipeline stage specs.
- Fail closed for host/container filesystem ambiguity. Path parity is strict in
  Stage 17 because persisted run-store and artifact paths are host paths.
- Redact before persistence. Values that may contain secrets never enter
  durable command, failure, provenance, diagnostic, or runtime metadata.
- Generic only where it is proven. Shared container records cover the fields
  Stage 17 and Stage 18 need; Docker behavior stays Docker-specific.
- Cheap by default. Default imports, tests, examples, and preflight must work
  without Docker, network, images, or registry access.
- Examples exercise product paths. Demonstrations should use the same executor
  and config surfaces as real runs, with fake runners only replacing the Docker
  command process in default validation.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Package ownership | Add shared records in `loom.pipeline.executors.containers`; add Docker behavior in `loom.pipeline.executors.docker` | Keeps Docker logic out of runner/runtime/diagnostics and preserves Stage 18 reuse |
| Public config namespace | Use shared `container` adapter options plus optional `docker` adapter options | Gives users a Stage 18-compatible public shape without hiding Docker-specific flags in generic fields |
| Executor lifecycle | `DockerExecutor.requires_prepared_worker_request = True` | Reuses parent-prepared durable worker request/result handling and parent finalization |
| Path semantics | Require path-parity mounts for run dirs and local artifact roots | Avoids host/container path translation in persisted run-store and artifact metadata |
| Environment | Pass explicit values or selected host names only; persist redacted summaries | Supports env-dependent stages without leaking secrets |
| Command execution | Use a narrow fakeable `DockerCommandRunner` and bounded result record | Enables deterministic tests and inspectable process facts without Docker SDK |
| Resources | Map basic CPU and memory; keep GPU unsupported in Stage 17 | Useful common Docker behavior without overpromising advanced runtime semantics |
| Provenance | Record Docker image/runtime/container facts as executor/provenance metadata by default | Adds reproducibility evidence without changing semantic fingerprints |
| Preflight | Add cheap Docker selected-executor checks with stable IDs | Gives actionable readiness diagnostics without daemon/network defaults |
| CLI | Extend `loom run --executor docker` and existing preflight selection; no Docker command group | Keeps CLI thin and avoids broad command surface |
| Reliability | Record process/timeout facts only; defer shared retry/timeout policy | Leaves Stage 19 to define cross-executor reliability semantics |
| Examples | Add daemon-free fake-runner examples/tests and optional live Docker notes | Satisfies stage/pipeline Docker examples without making Docker mandatory |

## Conflicts And Tradeoffs

- The shared `container` namespace is public surface. The plan constrains it to
  image, workdir, mounts, explicit environment handoff, and resource intent so
  Stage 18 can reuse it without inheriting Docker-specific behavior.
- Path parity is less flexible than path translation, but it avoids rewriting
  persisted file run URIs, worker request paths, and artifact-root metadata.
- Fake-command validation cannot prove every daemon-specific behavior, but it
  is the only default strategy consistent with deterministic CI and the no
  Docker dependency constraint. Optional live Docker smoke remains available.
- Recording Docker image/runtime facts as provenance rather than semantic
  fingerprints preserves resume behavior, but it means Stage 17 does not
  enforce image identity as part of the stage cache key.
- CPU and memory flags are useful but platform-specific in enforcement detail.
  Descriptor and diagnostics language must be precise and avoid promising more
  than Docker flags provide.

## Maintainability Assessment

The plan is maintainable if each phase preserves a narrow ownership boundary:
shared plain-data records first, Docker command construction second, executor
lifecycle integration third, diagnostics fourth, and examples/hardening last.
The main maintainability risks are public config creep, Docker behavior leaking
into generic records, CLI-owned command construction, and Docker executor code
starting to own parent finalization. Phase acceptance criteria and tests make
those risks explicit.

## Extensibility Assessment

The plan preserves Stage 18 by making container records generic enough for
Apptainer/Singularity bind/workdir/env/resource intent while keeping Docker
flags under `docker`. It preserves Stage 19 by recording process and failure
facts without adding executor-local retry policy. It preserves Stage 20 by
keeping committed Docker facts projectable into runtime events and event sinks.
It preserves Stage 21 and later cleanup by keeping container staging/log facts
derived, not authoritative artifact truth.

The plan does not introduce a universal cross-runtime command-runner
abstraction yet. That is deliberate: Stage 17 has only one new runtime, and
Stage 18 can justify a shared command-runner primitive if Docker and
Apptainer/Singularity prove enough common behavior.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Path-parity mounts only | Keeps Stage 17 correct with current file run URIs, worker requests, and local artifact-root metadata | Stage 18 or remote-store/container workflows need explicit host/container path translation |
| GPU unsupported | Advanced GPU mapping is deferred by the roadmap and differs across Docker, Apptainer, and schedulers | A future roadmap stage selects a concrete GPU mapping policy |
| Best-effort image digest metadata | Avoids default pulls, registry contacts, and daemon-heavy probes | Image lock files, image-as-semantic-input policy, or release acceptance requires stronger identity evidence |
| No default live Docker validation | Keeps default checks deterministic and available without Docker | Maintainers require live Docker acceptance before release |
| Narrow public `container` namespace | Preserves Stage 18 reuse without designing an orchestration API | Stage 18 needs incompatible generic fields or Docker-specific exceptions accumulate in shared records |
| Docker-local command runner | Avoids premature cross-runtime abstraction | Stage 18 duplicates enough command-runner shape to justify a shared primitive |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by `loom_plan_reviewer` on 2026-05-16; no blocking
  findings
- Refinement pass: not needed; review found no blockers or concerns requiring
  plan edits
- Confirmation review: complete by managing agent on 2026-05-16; no remaining
  blockers
- Automatic merge mode: enabled
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Default phase base/target: `develop`; each phase execution planner must
  recompute and record the actual stack predecessor and PR target before
  creating its worktree.
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Workflow path: expanded path expected for Phases 1-4 because they create or
  change public config, command protocols, executor lifecycle behavior,
  diagnostics contracts, and cross-module boundaries. Phase 5 may use the fast
  path unless validation or docs hardening exposes a concrete blocker.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `docker-container-contracts` | merged | `codex/docker-container-contracts` | [#171](https://github.com/samcantrill/loom/pull/171) | Shared container records, Docker descriptor, runtime/profile adapter contracts | Establish Stage 18-compatible container config and capability surface | Package, unit, contract, profile/descriptor tests; `make validate-pr`; `make test-summary` | Runtime/profile config snippets |
| 2 | `docker-command-runner` | merged | `codex/docker-command-runner` | [#172](https://github.com/samcantrill/loom/pull/172) | Docker options, command builder, command-runner protocol, process metadata | Build deterministic redacted Docker CLI commands and fakeable process results | Unit and contract tests for argv, redaction, resources, bounded output; `make validate-pr`; `make test-summary` | Prepared worker command projection |
| 3 | `docker-executor-integration` | merged | `codex/docker-executor-integration` | [#173](https://github.com/samcantrill/loom/pull/173) | `DockerExecutor`, CLI executor selection, prepared-worker result handling | Run stage attempts through Docker while preserving parent-owned finalization | Executor unit/integration, CLI fake-runner, failure mapping, regression tests; `make validate-pr`; `make test-summary` | Normal pipeline via `loom run --executor docker` |
| 4 | `docker-preflight-diagnostics` | merged | `codex/docker-preflight-diagnostics` | [#174](https://github.com/samcantrill/loom/pull/174) | Docker preflight check IDs, diagnostics, cheap readiness checks | Add selected-executor Docker diagnostics without daemon/network defaults | Unit, contract, JSON/preflight integration tests; `make validate-pr`; `make test-summary` | Docker preflight pass/fail examples |
| 5 | `docker-examples-acceptance` | pending | `codex/docker-examples-acceptance` | pending | Docs, examples, example tests, optional live Docker smoke | Publish stage/pipeline/failure examples and final validation evidence | Docs/config/example tests, optional marked live Docker smoke, full PR gate; `make validate-pr`; `make test-summary` | Stage, pipeline, failure, and optional live Docker examples |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Implementation-plan quality gate | Repository workflow | `loom_plan_reviewer` review and manager confirmation completed on 2026-05-16; no blocking findings remain and no refinement was required | resolved |

## Phase 1: Container Contracts And Runtime Descriptor

Status: merged
Slug: `docker-container-contracts`
Branch: `codex/docker-container-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/docker-container-contracts`
PR: [#171](https://github.com/samcantrill/loom/pull/171)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public adapter config
and reusable records for Stage 18

### Scope

- Goal: establish the shared container configuration and Docker capability
  contract that later Docker execution phases and Stage 18 can reuse.
- Files/modules owned:
  - new `src/loom/pipeline/executors/containers.py` or
    `src/loom/pipeline/executors/containers/`
  - Docker descriptor additions in `src/loom/pipeline/runtime/capabilities.py`
  - runtime/profile adapter namespace validation paths
  - focused unit, contract, and package import tests
- Behavior implemented:
  - Plain-data records for image reference, workdir, mounts, mount mode,
    explicit environment handoff, resource intent, path-parity validation
    summaries, and redacted command/metadata projection.
  - Public adapter namespace contract for shared `container` options and
    Docker-specific `docker` options.
  - Docker executor descriptor and resource capability declarations for
    CPU/memory support and GPU unsupported status.
  - Validation that rejects invalid mount targets, unsupported modes, invalid
    namespace payloads, and raw adapter payload persistence.
- Decisions applied: DAQ-1, DAQ-2, DAQ-4, DAQ-5, DAQ-7, DAQ-8, DAQ-10.
- Examples or docs covered: minimal runtime/profile config snippets for
  `adapter_options.container` and `adapter_options.docker`.
- Out of scope:
  - Docker command construction.
  - Docker process execution.
  - Docker preflight check execution beyond descriptor/config shape.
  - Apptainer/Singularity, SLURM-container composition, path translation, and
    semantic stage-spec Docker fields.
- Dependencies: landed runtime/profile adapter option behavior and descriptor
  registry.

### Tasks

- Define final shared container record names and serialization shape in the
  phase execution plan before implementation.
- Add strict plain-data validation and round-trip helpers for image, workdir,
  mount, environment, and resource intent.
- Add redaction helpers that can be reused by Docker command metadata and
  diagnostics without importing Docker command execution.
- Add Docker descriptor and adapter namespace claims for `container` and
  `docker`.
- Extend runtime/profile validation only where existing adapter option
  mechanics need explicit descriptor-backed behavior.
- Add tests proving shared records remain import-light and Docker behavior is
  not imported by default.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors tests/unit/loom/pipeline/runtime tests/contracts tests/package` | Target shared records, descriptor claims, adapter namespace contracts, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: shared records validate and serialize correctly, reject
  bad mounts/options, and expose redacted projections without Docker command
  execution.
- Design-decision evidence: generic `container` fields stay narrow and
  Docker-specific flags stay under `docker`.
- Future-roadmap compatibility evidence: records are usable by Stage 18
  Apptainer/Singularity planning without Docker imports or Docker flags.
- Interface, adapter, or protocol reuse evidence: descriptor namespace claims
  and resource capability declarations are explicit.
- Documentation evidence: examples or docstrings show the intended config
  shape.
- Domain-neutrality evidence: records use generic execution/container terms,
  not domain-specific pipeline assumptions.

### Phase Workflow State

- Phase execution plan: complete in
  `docs/roadmap/stage-17/phases/docker-container-contracts.md`
- Planning/refinement budget: expanded path draft and refine completed
- Implementation/refinement budget: not needed; targeted suites and full PR
  gate passed
- PR review budget: manager pre-submit review used; no blocking findings remain
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; PR opened against verified target branch
- Merge record: merged to `develop` by squash merge after CI success.

### Risks And Stop Conditions

- Risks: public config overreach, import cycles, Docker-specific leakage into
  shared records, or hidden semantic stage-spec changes.
- Stop conditions: Stage 18 reuse requires fields that contradict Docker
  needs; runtime/profile parsing needs a broader schema change than planned;
  shared records need Docker command execution imports.
- Assumptions: adapter options remain the public authored config surface for
  container behavior.

### Completion Summary

- Implementation: shared import-light container records, lazy executor package
  exports, Docker descriptor namespace/resource claims, and focused
  unit/contract/package coverage added.
- Validation: targeted phase tests passed (`105 passed`); broader phase suite
  passed (`479 passed, 3 skipped`); `make validate-pr` passed; `make
  test-summary` passed with `2180 passed, 18 skipped, 1765 deselected`.
- PR: [#171](https://github.com/samcantrill/loom/pull/171) opened against
  `develop` from `codex/docker-container-contracts`.
- Merge: [#171](https://github.com/samcantrill/loom/pull/171) merged into
  `develop` after GitHub CI `checks` passed and the PR target was reverified as
  `develop`.
- Follow-up: Phase 2 consumes these records for Docker command construction
  after Phase 1 merges or remains a valid stack predecessor.

## Phase 2: Docker Command Builder And Runner

Status: merged
Slug: `docker-command-runner`
Branch: `codex/docker-command-runner`
Worktree: `/home/samcantrill/work/loom-worktrees/docker-command-runner`
PR: [#172](https://github.com/samcantrill/loom/pull/172)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates a command-runner
protocol, process-result records, and redaction-sensitive metadata

### Scope

- Goal: build deterministic, shell-free, redaction-safe Docker CLI invocations
  and fakeable process result handling without integrating with parent runner
  finalization yet.
- Files/modules owned:
  - new `src/loom/pipeline/executors/docker/` module or package
  - Docker command builder and runner tests
  - command/result contract tests
- Behavior implemented:
  - Docker-specific option records and normalization.
  - Deterministic `docker run` argv construction for image, workdir, mounts,
    selected env, CPU/memory flags, log/result paths, and the prepared worker
    command.
  - Narrow `DockerCommandRunner` protocol with subprocess-backed default and
    fake test implementation.
  - Bounded `DockerCommandResult` record with return code, bounded stdout and
    stderr, process error facts, timing facts, timeout facts where available,
    and redacted command projection.
  - Best-effort Docker version and local image digest helpers that do not pull
    images or contact registries by default.
- Decisions applied: DAQ-2, DAQ-4, DAQ-5, DAQ-6, DAQ-7, DAQ-8, DAQ-11.
- Examples or docs covered: redacted prepared-worker Docker command projection
  in developer-facing docs or test fixtures.
- Out of scope:
  - `DockerExecutor` parent lifecycle integration.
  - Preflight presentation and stable check IDs.
  - CLI executor selection.
  - Real Docker acceptance as a required test.
- Dependencies: Phase 1 shared container records and descriptor/config shape.

### Tasks

- Define final Docker command/result protocol names and bounded output limits
  in the phase execution plan.
- Implement Docker argv construction using lists only, with deterministic
  ordering and no shell interpolation.
- Implement mount/workdir/env/resource flag construction using Phase 1 shared
  records.
- Implement redacted command and metadata projection before any durable
  persistence-facing values exist.
- Implement subprocess-backed runner and fake-runner test helpers.
- Implement cheap version/digest helpers behind Docker module ownership.
- Add tests for successful commands, invalid command inputs, subprocess
  exceptions, bounded output, redaction, CPU/memory flags, GPU unsupported
  handling, and no pull/registry behavior.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors tests/contracts tests/package` | Target Docker command builder, runner protocol, result serialization, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: Docker argv is deterministic, shell-free, and includes
  only validated mounts/env/resources.
- Design-decision evidence: runner protocol is Docker-local and fakeable; no
  Docker SDK is introduced.
- Future-roadmap compatibility evidence: result records are bounded and generic
  enough for Stage 19 reliability policy to consume later.
- Interface, adapter, or protocol reuse evidence: fake-runner tests exercise
  the same command/result protocol the executor will use.
- Documentation evidence: command projection examples are redacted.
- Domain-neutrality evidence: tests use generic stage-worker command fixtures.

### Phase Workflow State

- Phase execution plan: complete in
  `docs/roadmap/stage-17/phases/docker-command-runner.md`
- Planning/refinement budget: expanded path draft and refine completed
- Implementation/refinement budget: not needed; targeted suites and full PR
  gate passed
- PR review budget: manager pre-submit review used; no blocking findings remain
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; PR opened against verified target branch
- Merge record: merged to `develop` by squash merge after CI success.

### Risks And Stop Conditions

- Risks: leaking raw env values, shell-string construction, unbounded output,
  or command helpers reaching into runner lifecycle.
- Stop conditions: command construction requires path translation; Docker SDK
  becomes necessary; daemon-heavy image inspection is needed for default
  behavior.
- Assumptions: Docker command construction can be proven with fake runners by
  default.

### Completion Summary

- Implementation: Docker command package, option parsing, deterministic
  shell-free argv construction, redacted command projections, bounded command
  results, fake/subprocess runners, and cheap version/local image digest
  commands added.
- Validation: targeted phase tests passed (`66 passed`); broader phase suite
  passed (`460 passed, 3 skipped`); `make validate-pr` passed; `make
  test-summary` passed with `2194 passed, 18 skipped, 1779 deselected`.
- PR: [#172](https://github.com/samcantrill/loom/pull/172) opened against
  `develop` from `codex/docker-command-runner`.
- Merge: [#172](https://github.com/samcantrill/loom/pull/172) merged into
  `develop` after GitHub CI `checks` passed and the PR target was reverified as
  `develop`.
- Follow-up:

## Phase 3: Docker Executor Integration

Status: merged
Slug: `docker-executor-integration`
Branch: `codex/docker-executor-integration`
Worktree: `/home/samcantrill/work/loom-worktrees/docker-executor-integration`
PR: [#173](https://github.com/samcantrill/loom/pull/173)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase touches execution lifecycle,
CLI selection, failure semantics, and result metadata

### Scope

- Goal: run prepared stage attempts through Docker while preserving existing
  runner, worker-result, run-store, artifact-store, failure, and log semantics.
- Files/modules owned:
  - `src/loom/pipeline/executors/docker/`
  - lazy executor exports in `src/loom/pipeline/executors/__init__.py`
  - executor selection in `src/loom/cli/run.py`
  - focused executor, integration, and CLI tests
- Behavior implemented:
  - `DockerExecutor` with `requires_prepared_worker_request = True`.
  - Per-attempt option validation and path-parity mount preparation.
  - Docker process launch through `DockerCommandRunner`.
  - Standard worker result reading and normalization.
  - `StageExecutionResult` mapping for success, nonzero Docker process,
    missing worker result, invalid worker result, failed worker result,
    process/worker conflict, logs, exit code, and timeout/process facts.
  - CLI executor selection for `loom run CONFIG --executor docker`.
  - Redacted executor metadata persistence without raw adapter payloads or raw
    environment values.
- Decisions applied: DAQ-3, DAQ-4, DAQ-5, DAQ-6, DAQ-8, DAQ-10, DAQ-11,
  DAQ-12.
- Examples or docs covered: small fake-runner pipeline through
  `loom run --executor docker`.
- Out of scope:
  - Docker preflight check IDs and presentation.
  - Broad retry, timeout, transaction, event, or cleanup policy.
  - Docker-specific CLI command group.
  - Parent-owned finalization, artifact index writes, or run-store status
    authority inside the Docker executor.
  - Whole-controller-in-container mode.
- Dependencies: Phases 1 and 2.

### Tasks

- Define final executor metadata and failure-detail fields in the phase
  execution plan.
- Implement `DockerExecutor` as a prepared-worker executor.
- Wire CLI executor resolution and unsupported-executor messaging for Docker.
- Reuse existing worker command and result-reading conventions from
  `SubprocessExecutor` where appropriate.
- Add fake-runner integration tests for successful prepared worker execution
  and a small pipeline through the Docker executor.
- Add failure tests for nonzero Docker process, missing/invalid/failed worker
  result, worker/process conflict, log metadata, and redaction.
- Add regression tests proving local, subprocess, and SLURM selection still
  work.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/executors tests/integration tests/e2e tests/package` | Target executor lifecycle, CLI selection, fake-runner integration, and import regressions | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: `loom run --executor docker` can complete a small
  fake-runner pipeline using the prepared stage-worker path.
- Design-decision evidence: Docker executor returns results and metadata but
  parent runner owns finalization.
- Future-roadmap compatibility evidence: process/failure facts are recorded
  without adding Docker-local retry policy.
- Interface, adapter, or protocol reuse evidence: execution uses Phase 1
  records and Phase 2 command runner without bypassing them.
- Documentation evidence: example or test fixtures show normal pipeline Docker
  execution.
- Domain-neutrality evidence: example pipeline is generic and not tied to a
  research domain.

### Phase Workflow State

- Phase execution plan: complete in
  `docs/roadmap/stage-17/phases/docker-executor-integration.md`
- Planning/refinement budget: expanded path draft and refine completed
- Implementation/refinement budget: not needed; targeted suites, broad phase
  suite with config extra, and full PR gate passed
- PR review budget: manager automated review used; writable required-mount
  finding fixed before merge, with no blocking findings remaining
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; PR opened against verified `develop` target
- Merge record: PR [#173](https://github.com/samcantrill/loom/pull/173) merged
  into `develop` by squash merge after GitHub CI `checks` passed; merge commit
  `2333297486a08df5b694056d709ad9cf9fb75c58`; remote branch deleted.

### Risks And Stop Conditions

- Risks: Docker executor duplicating parent finalization, path-parity failures
  discovered too late, CLI growing Docker-specific behavior, or failure details
  leaking secrets.
- Stop conditions: prepared worker path cannot run with path-parity mounts;
  Docker execution requires path translation; CLI changes require a broad
  command redesign.
- Assumptions: the existing prepared-worker request/result contract is
  sufficient for Docker.

### Completion Summary

- Implementation: added `DockerExecutor` as a prepared-worker executor using
  Phase 1 container records and the Phase 2 Docker command runner; added
  required writable run-dir and artifact-root path-parity mounts; mapped Docker
  command facts and standard worker results into `StageExecutionResult`; kept
  Docker package/root executor exports lazy; wired `loom run --executor docker`;
  and added unit, integration, package, and CLI coverage.
- Validation: targeted Docker executor unit test passed (`14 passed`);
  `make validate-pr` passed with Ruff, Pyright, default harness (`1743 passed,
  26 skipped, 18 deselected`), config-extra harness (`440 passed, 1780
  deselected`), and build; `make test-summary` passed with overall `2211
  passed, 18 skipped, 1796 deselected`.
- PR: [#173](https://github.com/samcantrill/loom/pull/173) opened and verified
  against `develop` from `codex/docker-executor-integration`; GitHub CI
  `checks` passed.
- Review: manager automated review found and fixed a required writable
  run/artifact mount edge case before merge; no blockers remained.
- Merge: [#173](https://github.com/samcantrill/loom/pull/173) merged into
  `develop` by squash merge; merge commit
  `2333297486a08df5b694056d709ad9cf9fb75c58`; remote branch and stale local
  tracking ref were deleted.
- Follow-up: Phase 4 consumes the executor/container metadata and path checks
  for Docker selected-executor preflight diagnostics.

## Phase 4: Docker Preflight And Diagnostics

Status: merged
Slug: `docker-preflight-diagnostics`
Branch: `codex/docker-preflight-diagnostics`
Worktree: `/home/samcantrill/work/loom-worktrees/docker-preflight-diagnostics`
PR: [#174](https://github.com/samcantrill/loom/pull/174)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates stable diagnostics and
selected-executor preflight behavior

### Scope

- Goal: add cheap selected-executor Docker diagnostics that catch common
  runtime, filesystem, environment, and resource issues before launch.
- Files/modules owned:
  - `src/loom/diagnostics/models.py`
  - `src/loom/diagnostics/preflight.py`
  - preflight-facing Docker/container summary helpers
  - diagnostics contract/unit tests
- Behavior implemented:
  - Stable Docker check IDs for command availability, image reference
    presence, option shape, mount source/target validity, run-directory
    writability, local artifact-root visibility, required environment
    availability, CPU/memory support, and GPU unsupported errors.
  - Selected-executor behavior so Docker checks run when Docker is selected or
    explicitly inspected.
  - Structured JSON/details output that is actionable and redaction-safe.
  - Cheap default behavior: no image pulls, registry contacts, network probes,
    or daemon-heavy image inspection.
- Decisions applied: DAQ-4, DAQ-5, DAQ-7, DAQ-8, DAQ-9, DAQ-11.
- Examples or docs covered: Docker preflight pass/fail examples.
- Out of scope:
  - Expensive opt-in image pull or registry probes.
  - Real Docker daemon smoke as default validation.
  - Non-Docker container runtime preflight.
  - Reliability, event, transaction, or cleanup policy.
- Dependencies: Phases 1-3.

### Tasks

- Define final Docker preflight check IDs and severities in the phase
  execution plan.
- Add diagnostics model entries or constants where needed.
- Add preflight checks using shared records and Docker summaries without
  importing CLI presentation.
- Add tests for missing command, missing image reference, invalid mount source,
  relative or unsafe container target, read-only run directory, missing local
  artifact-root visibility, missing required env, CPU/memory mapping, GPU
  unsupported, JSON output, and selected-executor behavior.
- Add regression tests for local/subprocess/SLURM preflight.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/diagnostics tests/contracts tests/integration tests/package` | Target preflight check IDs, structured details, selected-executor behavior, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: Docker preflight reports actionable pass/fail diagnostics
  for command, config, filesystem, env, and resource issues.
- Design-decision evidence: checks are cheap by default and do not pull images
  or contact registries.
- Future-roadmap compatibility evidence: check pattern can be mirrored by
  Stage 18 container runtimes.
- Interface, adapter, or protocol reuse evidence: diagnostics consume shared
  summaries rather than Docker command internals.
- Documentation evidence: preflight examples show both pass and fail cases.
- Domain-neutrality evidence: messages describe generic execution readiness.

### Phase Workflow State

- Phase execution plan: complete in
  `docs/roadmap/stage-17/phases/docker-preflight-diagnostics.md`
- Planning/refinement budget: expanded path draft and refine completed
- Implementation/refinement budget: one `loom_phase_refiner` pass available if
  validation fails, check IDs are unstable, or diagnostics leak raw data
- PR review budget: manager pre-submit review used; no blocking findings remain
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; PR opened against verified `develop` target
- Merge record: PR [#174](https://github.com/samcantrill/loom/pull/174)
  merged into `develop` by squash merge after GitHub CI `checks` passed; merge
  commit `7471538b9fbdeae7f109b6006fd96c28cb5e714b`; remote branch deleted.

### Risks And Stop Conditions

- Risks: accidental daemon/network dependency, unstable check IDs, duplicate
  filesystem checks without Docker context, or raw env leakage in diagnostics.
- Stop conditions: default preflight requires real Docker daemon behavior;
  image availability cannot be represented without pulls; diagnostics need a
  broader preflight architecture change.
- Assumptions: cheap Docker readiness is useful even without proving image
  runtime availability.

### Completion Summary

- Implementation: added stable selected-Docker preflight diagnostics for Docker
  command availability, container/Docker option shape, image reference
  presence, required host environment variables, authored mount source
  existence, Stage 17 mount target path parity, run-directory writability,
  local artifact-root visibility, CPU/memory mapping, and unsupported GPU
  requests. Details are plain-data and redaction-safe, and default checks avoid
  Docker daemon, network, registry, image-pull, and SDK behavior.
- Validation: targeted Phase 4 suite passed (`87 passed, 2 skipped`);
  `uv run --extra config pytest tests/unit/loom/diagnostics tests/contracts
  tests/integration tests/package` passed (`666 passed`); `make validate-pr`
  passed with Ruff, Pyright, default harness (`1751 passed, 26 skipped, 18
  deselected`), config-extra harness (`442 passed, 1788 deselected`), and
  build; `make test-summary` passed with overall `2221 passed, 18 skipped,
  1804 deselected`.
- PR: [#174](https://github.com/samcantrill/loom/pull/174) opened and verified
  against `develop` from `codex/docker-preflight-diagnostics`.
- Merge: [#174](https://github.com/samcantrill/loom/pull/174) merged into
  `develop` by squash merge after GitHub CI `checks` passed; merge commit
  `7471538b9fbdeae7f109b6006fd96c28cb5e714b`; remote branch and stale local
  tracking ref were deleted.
- Follow-up: Phase 5 consumes the Docker preflight checks for docs, examples,
  failure inspection guidance, and optional live Docker smoke notes.

## Phase 5: Examples, Documentation, And Acceptance Hardening

Status: pending
Slug: `docker-examples-acceptance`
Branch: `codex/docker-examples-acceptance`
Worktree: `/home/samcantrill/work/loom-worktrees/docker-examples-acceptance`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless docs/example validation exposes a concrete
blocker or optional live Docker acceptance changes public behavior

### Scope

- Goal: provide the requested Docker stage and pipeline examples, then harden
  final validation evidence for review.
- Files/modules owned:
  - Docker sections in feature docs and user docs
  - example configs and fixtures
  - docs/example tests
  - optional marked live Docker smoke or manual acceptance note
- Behavior implemented:
  - Docs/examples for direct/prepared stage Docker execution.
  - Docs/examples for normal `loom run --executor docker` pipeline execution.
  - Docker preflight examples.
  - Inspectable Docker failure examples.
  - Runtime/profile configuration examples using `container` and `docker`
    adapter namespaces.
  - Optional real Docker smoke guidance or marked test gated outside default
    validation.
- Decisions applied: FR-10 and DAQ-12, plus non-goal/safety language from the
  design-safety review.
- Examples or docs covered: all Stage 17 example obligations.
- Out of scope:
  - Image build, registry auth, Compose, Kubernetes, Apptainer/Singularity,
    advanced GPU mapping, and controller-in-container examples.
  - Requiring real Docker in `make validate-pr`.
  - Presenting Docker as a sandbox for untrusted code.
- Dependencies: Phases 1-4.

### Tasks

- Add or update feature/user docs for Docker executor behavior, config, and
  non-goals.
- Add example config(s) for stage and pipeline Docker execution using
  `container` and `docker` adapter options.
- Add fake-runner example tests that prove examples exercise product paths.
- Add failure/preflight example fixtures and expected inspection guidance.
- Add optional live Docker smoke or manual acceptance notes if implementation
  scope allows, gated outside default validation.
- Run full validation and record final suite evidence for PR preparation.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit tests/contracts tests/integration tests/e2e tests/package` | Target docs/config/example tests plus broad regression coverage | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |
| Optional marked live Docker smoke | Prove a tiny pipeline against real Docker when explicitly enabled | no |

### Acceptance Evidence

- Behavior evidence: examples show stage and pipeline Docker workflows through
  actual product config/executor paths.
- Design-decision evidence: examples use `container` plus `docker` namespaces,
  path-parity mounts, explicit env, and redacted failure/preflight output.
- Future-roadmap compatibility evidence: docs state Apptainer/Singularity and
  SLURM-container composition remain Stage 18 work.
- Interface, adapter, or protocol reuse evidence: example tests use the same
  fake-runner extension points as executor tests.
- Documentation evidence: docs include preflight, failure inspection, non-goals,
  and optional live Docker validation.
- Domain-neutrality evidence: examples use generic local/CI pipeline behavior.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: fast path by default; refine only if examples or
  validation expose unresolved public behavior
- Implementation/refinement budget: zero on fast path, one available if final
  validation fails or example coverage is missing
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phase 4 merged or valid as stack predecessor
- Merge record: pending

### Risks And Stop Conditions

- Risks: examples drift into unsupported whole-controller mode, require real
  Docker by default, imply a security sandbox, or fail to exercise product
  paths.
- Stop conditions: examples require product behavior not implemented by Phases
  1-4; optional live Docker acceptance becomes mandatory for release; docs need
  a broad user-guide restructure.
- Assumptions: daemon-free fake-runner examples are sufficient default
  validation.

### Completion Summary

- Implementation:
- Validation:
- PR:
- Merge:
- Follow-up:

## Cross-Phase Validation

- Full relevant test command: `make validate-pr`
- PR evidence command: `make test-summary`
- Docs/template checks: examples and docs must stay consistent with
  `docs/features/container-executors.md`, `docs/features/execution.md`,
  `docs/features/runtime-resources.md`, `docs/features/preflight.md`,
  `docs/features/provenance.md`, `docs/features/reliability.md`, and
  `docs/features/testing.md`.
- Domain-neutrality checks: no examples or APIs should assume a research
  domain, a specific registry, a cloud provider, or a service-specific
  container workflow.
- Example/demo checks: default examples are fake-runner or docs/config based;
  optional real Docker smoke must be clearly skipped unless explicitly enabled.
- Manual review focus: public `container`/`docker` config shape, path-parity
  failure behavior, redaction before persistence, no Docker SDK dependency,
  cheap preflight defaults, lifecycle ownership in `PipelineRunner`, and
  existing executor regression safety.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| None | N/A | `loom_plan_reviewer` found no blocking plan-quality issues. Planning readiness, design-safety evidence, future-roadmap compatibility, reusable interface assumptions, phase boundaries, and suite obligations are sufficiently traced for phase work. | resolved |

Gate result:

- Status: passed
- Review evidence:
  - `loom_plan_reviewer` review on 2026-05-16 found no blocking plan-quality
    issues and no required refinement.
  - Manager confirmation review on 2026-05-16 verified the only prior blocker
    was the self-referential pending quality-gate metadata, which this update
    resolves.
- Accepted risks:
  - Path-parity mounts only.
  - GPU mapping unsupported.
  - Best-effort image digest metadata.
  - No default real Docker validation.
  - Narrow public `container` namespace.
  - Docker-local command runner for Stage 17.
- Revisit triggers:
  - Stage 18 needs incompatible container fields, path translation, or
    scheduler/container resource composition.
  - A future image-lock, image-as-semantic-input, secret-management, or
    expensive-preflight stage changes provenance or redaction policy.
  - Maintainers require live Docker acceptance evidence before release.
  - Multiple container runtimes duplicate enough command-runner behavior to
    justify a shared command operation primitive.

## Final Approval

- Approval status: approved for phase execution planning.
- Approved scope: Phase 1 through Phase 5 as recorded in this implementation
  plan, with each phase requiring a scope-complete phase execution plan before
  implementation.
- Accepted risks: path-parity mounts only, GPU unsupported, best-effort image
  digest metadata, no default live Docker validation, narrow public
  `container` namespace, and Docker-local command runner for Stage 17.
- Deferred items: image builds, registry auth, automatic pulls, Compose,
  Kubernetes, Apptainer/Singularity, SLURM-container composition, advanced GPU
  mapping, whole-controller container mode, Docker security-sandbox claims,
  broad retry/timeout/event/transaction policy, cleanup/retention policy, and
  required live Docker validation.
