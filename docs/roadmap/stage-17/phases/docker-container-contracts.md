# Phase 1 Execution Plan: Container Contracts And Runtime Descriptor

## Metadata

- Status: pr_open
- Feature focus: Docker Container Executor
- PR title: `Docker Container Executor - Phase 1: Container Contracts And Runtime Descriptor`
- Branch: `codex/docker-container-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/docker-container-contracts`
- Phase execution plan path: `docs/roadmap/stage-17/phases/docker-container-contracts.md`
- Full plan: `docs/roadmap/stage-17/implementation-plan.md`
- Source phase: Stage 17 Phase 1, `docker-container-contracts`
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- PR: [#171](https://github.com/samcantrill/loom/pull/171)
- Merge eligibility: root phase, eligible to merge to `develop` after implementation, validation, PR preparation, and automated review pass
- Workflow path: expanded path
- Successor dependency notes: Phase 2 `docker-command-runner` depends on this branch until Phase 1 merges or is a valid stack predecessor.
- Plan quality gate: passed in the implementation plan on 2026-05-16 with no blockers
- Plan quality gate loop budget: consumed before phase planning; no additional plan-quality review assigned here
- Draft pass: completed in commit `894857d`
- Refine pass: completed in this planning pass
- Setup limitations: Stage 17 source docs were copied from the dirty control checkout because they are not on `develop`; no `docs/roadmap.md` or stage 19 files are copied or edited.
- Blockers: none

## Objective

Establish the Stage 17 public container configuration and capability contract
without implementing Docker command construction or execution. This phase gives
later Docker phases and Stage 18 import-light shared records for image,
workdir, mounts, explicit environment handoff, resource intent, path-parity
summaries, and redacted metadata projection, plus a Docker runtime descriptor
that claims the `container` and `docker` adapter namespaces.

## Full-Plan Context

Stage 17 adds a Docker CLI-backed executor through five phases. This first
phase is the public contract foundation: shared container records and Docker
descriptor/profile wiring. Phase 2 builds Docker argv and runner records from
these contracts, Phase 3 uses them in `DockerExecutor`, Phase 4 adds Docker
preflight diagnostics, and Phase 5 publishes examples and final hardening.

Future-phase work that must stay out of this PR includes Docker argv
construction, process execution, preflight check execution, CLI executor
selection, worker-result handling, provenance collection, Apptainer/Singularity,
SLURM-container composition, image pulls, registry auth, and live Docker tests.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Stage 16 is recorded complete and Stage 17
  Phase 1 has no earlier unmerged Stage 17 predecessor.
- Retarget/rebase plan after predecessor merge: not applicable for this root
  phase; successor branches should rebase or retarget to `develop` after this
  phase merges.
- Branch cleanup constraints: do not delete `codex/docker-container-contracts`
  while any successor phase still targets or branches from it.

## Source Phase Summary

- Goal: establish shared container configuration records and the Docker
  capability surface.
- Required scope: import-light container records under executor ownership,
  Docker descriptor/capability declarations, `container` and `docker` adapter
  namespace claims, targeted runtime/profile validation hooks, and focused
  package/unit/contract tests.
- Required checkpoints: final shared record names and serialization shape,
  redaction helpers, path-parity validation summaries, resource capability
  language, and no raw adapter payload persistence.
- Acceptance criteria: records validate and serialize deterministically, reject
  invalid mounts/options, expose redacted projections without Docker command
  execution, keep `container` narrow and Docker flags under `docker`, and avoid
  Docker imports in package/runtime boundaries.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/runtime/capabilities.py` owns `ExecutorDescriptor`,
    `ResourceCapability`, adapter namespace claims, the default descriptor
    registry, and capability diagnostics.
  - `src/loom/pipeline/runtime/profiles.py` already normalizes non-core
    profile sections into `adapter_options` and rejects duplicate namespace
    payloads.
  - `src/loom/pipeline/runtime/options.py` owns strict plain-data parsing for
    `RunOptions` and `StageRuntimeOptions`.
  - `src/loom/pipeline/runtime/metadata.py` summarizes runtime options without
    persisting raw adapter payloads or environment values.
  - `src/loom/pipeline/executors/__init__.py` is the package import boundary
    that must stay lightweight.
- Existing tests or harness behavior:
  - `tests/unit/loom/pipeline/test_executor_capabilities.py` and
    `tests/contracts/test_executor_capabilities_contract.py` cover descriptor
    serialization, registry contents, resource diagnostics, adapter namespace
    warnings, and import boundaries.
  - `tests/unit/loom/pipeline/test_runtime_profiles.py` and
    `tests/contracts/test_runtime_profiles_contract.py` cover profile
    normalization and merge behavior.
  - `tests/package/test_import_boundaries.py` and
    `tests/package/test_pipeline_executor_api.py` are the package suites most
    likely to catch eager Docker imports.
- Import-boundary or dependency constraints: no Docker SDK, no daemon-facing
  module imports, no CLI/diagnostics/runtime presentation imports from shared
  container records, and no broad runtime schema rewrite.

## In-Scope Work

- Add import-light shared container value records and validation helpers under
  `loom.pipeline.executors.containers` or an equivalent `containers/` package.
- Define and test the public plain-data contract for `adapter_options.container`.
- Claim `container` and `docker` adapter namespaces on the built-in Docker
  descriptor.
- Add Docker resource capability declarations: CPU and memory are Docker-mapped
  with best-effort enforcement language; GPU is unsupported/error in Stage 17.
- Provide reusable redaction helpers for command, metadata, diagnostics, and
  future executor persistence without importing Docker command behavior.
- Add narrow runtime/profile tests that prove profile shorthand and explicit
  `adapter_options` produce valid container/Docker namespace payloads.
- Add package/import tests proving shared container records do not import Docker
  command modules, diagnostics, CLI, execution, stores, optional SDKs, network,
  or daemon-facing code.
- Add a minimal runtime/profile config snippet in tests, module docs, or a
  narrow feature-doc section showing `container` for generic fields and
  `docker` reserved for Docker-specific fields. Broad user-facing examples stay
  in Phase 5.

## Out-of-Scope Work

- Docker argv construction, process execution, runner protocol, or process
  result records.
- `DockerExecutor`, CLI `--executor docker` selection, worker result handling,
  log capture, executor metadata persistence, and provenance collection.
- Docker preflight check IDs or selected-executor preflight execution.
- Apptainer/Singularity, `singularity` aliases, SLURM-container composition,
  path translation, Docker Compose, Kubernetes, image builds, image pulls,
  registry auth, image lock files, advanced GPU mapping, or sandbox guarantees.
- Adding Docker fields to semantic pipeline stage specs.

## Assumptions

- Authored runtime/profile config is trusted project code, but raw adapter
  payloads and raw environment values are not safe to persist.
- Resource requests remain scheduler-neutral in existing `ResourceRequest`
  records; this phase only creates container-facing intent/projection helpers.
- Runtime/profile merge semantics stay as they are; this phase extends
  descriptor-backed validation and container parsing rather than redesigning
  profile composition.
- Phase 2 may add Docker-specific option records under Docker ownership, but
  Phase 1 reserves and claims the `docker` namespace now to avoid warning on
  valid future Docker profile sections.

## Scope Contract

Public shared records must be plain-data, frozen, deterministic, and
Stage 18-neutral. Use existing repository patterns such as dataclasses,
`StrEnum`, `to_dict()`/`from_dict()`, sorted mappings, and strict unknown-field
rejection.

Target shared record names and serialized shapes:

- `ContainerImageReference`: `{reference: str}`. The reference must be
  non-empty after stripping. Digest resolution and image inspection are not part
  of this phase.
- `ContainerMountMode`: enum values `ro` and `rw`.
- `ContainerMount`: `{source: str, target: str, mode: "ro" | "rw"}`. Source
  is an explicit host path string. Target must be absolute. Mode is required;
  no implicit mount mode is introduced in the public contract.
- `ContainerEnvironment`: `{variables: Mapping[str, str], required_host_variables: list[str]}`.
  `variables` are explicit values supplied by config. `required_host_variables`
  are host names the executor may resolve at launch. Full host environment
  inheritance is not represented.
- `ContainerResourceIntent`: `{entries: Mapping[str, PlainData], capabilities: Mapping[str, PlainData]}`.
  Entries mirror existing `ResourceEntry.to_dict()` payloads; capabilities
  mirror `ResourceCapability.to_dict()` payloads so command builders can decide
  later what to map.
- `ContainerPathParitySummary`: `{kind: str, host_path: str, container_path: str, writable_required: bool, ok: bool, reason: str | None}`.
  It is a validation summary, not a path-translation protocol.
- `ContainerOptions`: `{image: ContainerImageReference, workdir: str | None, mounts: list[ContainerMount], environment: ContainerEnvironment, resources: ContainerResourceIntent | None}`.
  Image is required for Docker execution. Workdir, mounts, environment, and
  resources stay generic. Resource intent is derived from existing runtime
  resource requests and descriptor capabilities; this phase must not add a
  second authored resource surface under `container`.
- `RedactedContainerMetadata`: plain-data projection with image reference,
  workdir, mount summaries, selected environment key names, redacted explicit
  env values when needed, and resource support summaries. It must not include
  raw adapter payloads or raw host environment values.

Adapter namespace contract:

- `adapter_options.container` carries the generic `ContainerOptions` payload.
- Runtime profile shorthand `container:` may normalize into
  `adapter_options.container` through existing profile behavior.
- `adapter_options.docker` is claimed by the Docker descriptor but remains
  Docker-owned. In Phase 1 it may be an empty or strictly reserved plain
  mapping; it must reject generic container fields such as `image`, `workdir`,
  `mounts`, `environment`, and `resources` when supplied under `docker`.
- Capability validation may warn for unclaimed namespaces but must not inspect
  or persist raw namespace payloads.
- The built-in Docker descriptor name is `docker`. It should be present in
  `DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY`, claim `("container", "docker")` after
  deterministic sorting, and use details that describe it as built-in,
  containerized, CLI-backed, and not a Docker SDK dependency.

Error behavior and edge cases:

- Reject unknown container fields, non-mapping payloads, empty image strings,
  relative or empty mount targets, unsupported mount modes, non-string
  environment names, non-string explicit env values, duplicate mount targets,
  and resource intent entries that are not already valid `ResourceEntry`
  payloads.
- Reject or clearly summarize non-path-parity run/artifact paths without
  adding remapping behavior.
- Redact before any value is handed to command metadata, diagnostics, runtime
  metadata, or failure metadata helpers.

## Design Impact

- Maintainability: shared records keep container parsing and redaction in one
  import-light executor-owned module; Docker command code can consume records
  later instead of parsing raw dictionaries repeatedly.
- Extensibility: Stage 18 can reuse image/workdir/mount/env/resource records
  for Apptainer/Singularity without inheriting Docker flags.
- Domain neutrality: config names describe generic container execution, not a
  research domain, registry provider, scheduler site, or cloud platform.
- Source-tree boundaries: runtime descriptors claim capabilities; executors own
  adapter parsing; diagnostics and CLI remain consumers in later phases.

## Future Compatibility

- Stage 18 may add Apptainer/Singularity records around the same generic
  `container` payload while keeping runtime-specific flags out of the generic
  namespace.
- Stage 19 can consume process/failure facts emitted later without this phase
  adding retry, timeout, or failure-category policy.
- Stage 20 can project redacted container facts into runtime events because the
  records are plain data.
- Stage 21 cleanup can use derived path/log facts without treating container
  mounts as artifact authority truth.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put all authored container config under `docker` | Would force Stage 18 migration or duplicate generic image/workdir/mount/env fields. |
| Add Docker fields to semantic pipeline stage specs | Would make pipeline definitions executor-specific and change fingerprint/resume expectations. |
| Add a broad orchestration API now | Stage 17 only needs per-stage Docker execution; Compose, Kubernetes, and whole-controller mode are out of scope. |
| Implement host/container path translation in Phase 1 | Current worker and run-store metadata use host paths; translation needs a future design. |
| Eagerly import Docker executor behavior from runtime or package APIs | Violates optional Docker dependency and import-light boundaries. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Path parity is the only mount strategy | Keeps Stage 17 correct with current run-store and artifact path metadata | Stage 18 or remote/local hybrid stores need explicit path translation. |
| Docker `docker` namespace is claimed before all Docker-specific fields exist | Avoids false unclaimed-namespace warnings while Phase 2 defines command options | Phase 2 cannot represent required Docker flags without changing Phase 1 public contract. |
| CPU/memory enforcement is described as best effort | Docker behavior varies by daemon/platform and the descriptor should not overpromise | Maintainers choose a stricter cross-platform Docker resource policy. |

## Reviewability

- Expected PR size and shape: small-to-medium public contract PR touching a new
  shared container module, runtime capability registry, runtime/profile tests,
  contracts, and package import tests.
- Files and areas to inspect: container record naming and serialization,
  descriptor `adapter_namespaces`, Docker CPU/memory/GPU capability details,
  profile shorthand normalization, no raw adapter/env persistence, and import
  boundaries.
- Scope-control checks: no Docker command builder, no subprocess invocation,
  no preflight check IDs, no CLI selection, no Docker SDK, and no semantic
  stage-spec fields.

## Implementation Steps

1. Add the shared container records and strict parse/serialization helpers under
   executor ownership.
2. Add redacted projection and path-parity summary helpers that operate on the
   shared records without Docker imports.
3. Add the Docker executor descriptor to the default registry with `container`
   and `docker` namespace claims and precise CPU/memory/GPU resource capability
   details.
4. Extend runtime/profile validation only where needed to validate or preserve
   the new namespace contract through existing merge behavior.
5. Add the minimal config snippet showing `container` versus `docker`
   namespace ownership.
6. Add focused package, unit, and contract coverage for records, descriptors,
   profile namespaces, redaction, persistence boundaries, and import-light
   behavior.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_executor_api.py`, and/or adjacent package API
  tests.
- Required assertions or deferral reason: importing `loom.pipeline.runtime` and
  shared container records must not import Docker command modules, diagnostics,
  CLI, execution, optional SDKs, or daemon-facing behavior; public package
  exports remain lightweight.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/test_containers.py`,
  `tests/unit/loom/pipeline/test_executor_capabilities.py`, and
  `tests/unit/loom/pipeline/test_runtime_profiles.py`.
- Required assertions or deferral reason: valid/invalid value records,
  serialization round trips, mount target and mode validation, duplicate mount
  targets, explicit env and required host names, redacted metadata projection,
  path-parity summary behavior, Docker descriptor capabilities, and profile
  namespace normalization.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_executor_capabilities_contract.py`,
  `tests/contracts/test_runtime_profiles_contract.py`, and a new or adjacent
  container contract test.
- Required assertions or deferral reason: plain-data contract stability,
  `container`/`docker` namespace claims, unclaimed namespace diagnostics remain
  payload-inspection-free, no raw adapter payload persistence, and Stage
  18-neutral naming.

### Integration Suite

- Status: deferred for this phase.
- Expected paths: none required before Phase 3.
- Required assertions or deferral reason: this phase does not execute Docker or
  run prepared workers; integration coverage begins when Docker command and
  executor paths exist.

### E2E Suite

- Status: deferred for this phase.
- Expected paths: none.
- Required assertions or deferral reason: CLI `--executor docker` selection and
  end-to-end fake Docker execution are Phase 3/5 work.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: live Docker smoke is optional Phase 5
  work and must stay outside default validation.

## Risks

- Public `container` config grows beyond image/workdir/mount/env/resource
  intent and becomes hard for Stage 18 to reuse.
- Descriptor resource language overstates Docker enforcement or hides GPU
  unsupported behavior.
- Shared records accidentally import Docker command code, diagnostics, CLI, or
  execution modules.
- Runtime/profile validation starts persisting raw adapter payloads or raw env
  values.
- Phase 1 adds command/execution behavior that belongs in Phases 2 and 3.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/test_containers.py
uv run pytest tests/unit/loom/pipeline/test_executor_capabilities.py tests/unit/loom/pipeline/test_runtime_profiles.py
uv run pytest tests/contracts/test_executor_capabilities_contract.py tests/contracts/test_runtime_profiles_contract.py
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_executor_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: shared records first, descriptor registry second,
  profile/namespace validation third, tests throughout.
- Tests to run with each slice: run the closest unit test file after records,
  descriptor unit/contract tests after registry changes, and package import
  tests after any export changes.
- Decisions the executor must not revisit: use `container` for generic options,
  reserve `docker` for Docker-specific options, require path parity, keep GPU
  unsupported, do not persist raw env or adapter payloads, and do not add Docker
  command or executor behavior.
- Conditions that require stopping for the manager: implementation needs path
  translation, a runtime schema rewrite, a Docker SDK, eager Docker imports,
  semantic stage-spec fields, or broader Docker-specific options than Phase 1
  can safely define.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted suites, broader phase
  suites, `make validate-pr`, and `make test-summary` passed after manager
  implementation.
- PR review: manager pre-submit review used; image adapter serialization shape
  was tightened before PR preparation, and no blocking findings remain.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in commit `894857d`.
- Final phase execution plan: refined in this assignment and ready for implementation.
- Implementation summary: implemented shared import-light container records in
  `loom.pipeline.executors.containers`, lazy executor package exports, Docker
  descriptor namespace/resource claims, and focused unit/contract/package
  coverage for serialization, validation, redaction, profile namespaces, and
  import boundaries. Implementation commits: `cca4723`, `5c0dc19`.
- Implementation validation:
  - `uv run pytest tests/unit/loom/pipeline/executors/test_containers.py tests/unit/loom/pipeline/test_executor_capabilities.py tests/unit/loom/pipeline/test_runtime_profiles.py tests/contracts/test_container_executor_contract.py tests/contracts/test_executor_capabilities_contract.py tests/contracts/test_runtime_profiles_contract.py tests/package/test_import_boundaries.py tests/package/test_pipeline_executor_api.py` passed: 105 passed.
  - `uv run pytest tests/unit/loom/pipeline/executors tests/unit/loom/pipeline/test_executor_capabilities.py tests/unit/loom/pipeline/test_runtime_profiles.py tests/unit/loom/pipeline/test_runtime_metadata.py tests/contracts tests/package` passed: 479 passed, 3 skipped.
  - `make validate-pr` passed: ruff, pyright, default harness, config-extra harness, and build.
  - `make test-summary` passed and wrote `build/test-summary.md`; overall 2180 passed, 18 skipped, 1765 deselected.
- Refinement summary: tightened status, public record shapes, descriptor
  expectations, namespace ownership, and minimal snippet obligations.
- Blocker-resolution summary: none used.
- PR preparation: complete; [#171](https://github.com/samcantrill/loom/pull/171)
  opened against `develop` and verified with `gh pr view`.
- Stack maintenance: root phase from `develop`; no predecessor.
- Remaining blockers: none.
