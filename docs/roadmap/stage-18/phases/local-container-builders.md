# Phase 2 Execution Plan: Local Build Service And Runtime Builders

## Metadata

- Status: in_progress
- Feature focus: HPC Container Execution
- PR title: `HPC Container Execution - Phase 2: Local Container Builders`
- Branch: `codex/local-container-builders`
- Worktree: `/home/samcantrill/work/loom-worktrees/local-container-builders`
- Phase execution plan path: `docs/roadmap/stage-18/phases/local-container-builders.md`
- Full plan: `docs/roadmap/stage-18/implementation-plan.md`
- Source phase: Stage 18 Phase 2, `local-container-builders`
- Stack predecessor: none
- Base branch: `origin/develop` at `b5d5967`
- Target branch: `develop`
- PR: pending
- Merge eligibility: root phase; merge to `develop` after validation and automated review
- Workflow path: expanded path
- Successor dependency notes: Phase 3 depends on resolved output refs and build-service result shapes.
- Plan quality gate: passed in the implementation plan on 2026-05-17
- Draft pass: completed by manager before implementation
- Refine pass: completed in this planning pass because this phase adds request/result protocol behavior and runtime command semantics
- Blockers: none

## Objective

Implement deterministic local build/reuse behavior for Phase 1 `container_build` targets without adding daemon, registry, site-service, or SDK dependencies. This phase adds an import-light local service/fake builder protocol, policy decisions for `if_stale`, `always`, and `never`, Docker build command construction through the existing Docker runner contract, and build-only Apptainer/Singularity command construction for SIF outputs.

## In-Scope Work

- Extend `loom.pipeline.executors.containers` with shared build action/policy decisions, a builder protocol, a local dispatch service, and a deterministic fake builder.
- Add Docker build helpers under `src/loom/pipeline/executors/docker/` that build `docker build` argv from shared requests and execute through the existing fakeable Docker command runner.
- Add build-only Apptainer helpers under `src/loom/pipeline/executors/apptainer/` with options, command/result records, fake/subprocess runners, and a SIF builder adapter.
- Add local output probes that avoid network-backed source fetches by default: Docker uses local image inspection only, and Apptainer uses local SIF path existence/mtime checks.
- Record redacted command projections, bounded evidence metadata, output refs, and structured failures for build, reuse, skipped, and failed results.
- Add unit, contract, integration, and package tests for policy decisions, fake service behavior, command construction, redaction, local reuse/failure, and import boundaries.

## Out-of-Scope Work

- External/site build services, daemon queues, registry login, image publishing, global cache, image lock files, and automatic image conversion.
- Direct Apptainer stage execution, `apptainer exec`, prepared worker launch, and SLURM script composition.
- Network staleness probes, Docker pulls, remote Apptainer build, site modules, path translation, and MPI/rank policy.

## Assumptions

- `if_stale` may reuse a local Docker image when local inspect succeeds; it does not pull or compare remote image state.
- Apptainer source staleness uses local path mtimes only when the source is local and inspectable; URI sources rebuild only when the output is absent or policy is `always`.
- Build args may be recorded as names and redacted values, but runtime-specific builders decide which flags they support.
- The build service dispatches one request at a time in foreground and returns shared `ContainerBuildResult` records.

## Design Impact

- Maintainability: shared policy and fake service tests prevent Docker and Apptainer builders from diverging on `always`, `if_stale`, and `never`.
- Extensibility: future external/site builders can implement the same protocol without changing target records.
- Domain neutrality: builders consume user-authored contexts, definition files, local paths, and URIs; Loom does not generate project recipes.
- Source-tree boundaries: shared build dispatch remains import-light; runtime command behavior stays under Docker or Apptainer modules.

## Future Compatibility

- Phase 3 can consume resolved Docker image/SIF refs without owning build policy.
- Phase 4 can require submit-side build resolution before SLURM dry-run/live rendering.
- Stage 19 can classify build failure facts separately from launch and worker failure facts.
- Future image locks or external builders can replace local probes behind the same request/result contract.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put Docker and Apptainer build execution in `containers.py` | Would break the import-light shared record boundary. |
| Add a daemon or queue-backed build service now | Stage 18 only requires foreground local build/reuse. |
| Pull or inspect remote registries for staleness | Default validation must stay fake/local/offline and avoid auth policy. |
| Reuse Docker command-runner implementation for Apptainer | The command surfaces differ enough that adapter-local runners are clearer. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Docker `if_stale` reuses local inspect success without source freshness | There is no durable image lock/cache contract in Stage 18 | Image locks, semantic image identity, or registry freshness policy is selected. |
| Apptainer URI staleness is not probed | Avoids network access and auth assumptions | Remote build/source freshness becomes an explicit feature. |
| Apptainer build runner is build-only | Direct execution belongs to Phase 3 | Phase 3 adds enough common runner behavior to justify a shared Apptainer command module. |

## Reviewability

- Expected PR size and shape: medium adapter PR touching shared container build dispatch, Docker build helpers, a new Apptainer build module, tests, and phase metadata.
- Files and areas to inspect: policy decision mapping, output probe behavior, Docker/Apptainer argv, redaction, failure classification, import boundaries, and no hidden runtime execution.
- Scope-control checks: no `apptainer exec`, no SLURM wrapping, no registry auth, no image locks, no network staleness checks, and no SDK dependencies.

## Implementation Steps

1. Add shared build action/policy decision records, local service dispatch, and fake builder behavior.
2. Add Docker build command construction and a local Docker builder adapter over the existing Docker command runner.
3. Add Apptainer build options, command/result records, fake/subprocess runner, and SIF builder adapter.
4. Add targeted unit/contract/integration/package coverage and update public exports where needed.
5. Run targeted suites, full validation, test summary, PR body preparation, and automated review.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package`.
- Required assertions or deferral reason: importing shared container records must not import Docker/Apptainer command modules; importing package surfaces remains optional-dependency light.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/test_containers.py`, `tests/unit/loom/pipeline/executors/docker/test_build.py`, `tests/unit/loom/pipeline/executors/apptainer/test_build.py`.
- Required assertions or deferral reason: policy decisions, fake service, Docker argv/redaction, Apptainer argv/redaction, local output probes, failure records, and bounded evidence.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_container_executor_contract.py`.
- Required assertions or deferral reason: shared request/result/service records stay plain data and adapter-neutral.

### Integration Suite

- Status: required.
- Expected paths: focused fake-runner tests under `tests/integration/pipeline/`.
- Required assertions or deferral reason: fake Docker/Apptainer builders deterministically build, reuse, and fail without real runtimes.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: CLI execution and SLURM composition remain later phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: real Docker/Apptainer smoke.
- Required assertions or deferral reason: real runtime smoke is Phase 5 optional work.

## Risks

- Build metadata leaks raw build args or command environment values.
- Policy decisions imply stronger cache or image-lock semantics than implemented.
- Docker or Apptainer builders silently accept incompatible target/output shapes.
- Shared service imports runtime modules and breaks package import boundaries.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/test_containers.py tests/unit/loom/pipeline/executors/docker/test_build.py tests/unit/loom/pipeline/executors/apptainer/test_build.py
uv run pytest tests/contracts/test_container_executor_contract.py
uv run pytest tests/integration/pipeline/test_container_builders.py
uv run pytest tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes

- Safe implementation slices: shared policy/fake service first, Docker build adapter second, Apptainer build adapter third, integration/package coverage last.
- Tests to run with each slice: closest unit tests after each adapter, contract tests after shared record changes, package tests after imports/exports.
- Decisions not to revisit: foreground local build only, no registry/auth/global cache/image locks, no direct execution, no SLURM composition, no network freshness checks.
- Stop conditions: policy requires cache/image-lock semantics, Apptainer behavior requires site assumptions not expressible in records, or Docker compatibility requires Stage 17 executor contract changes.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager in this file before code changes.
- Final phase execution plan: refined in this planning pass; ready for implementation.
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- PR preparation: pending
- Stack maintenance: root phase from `develop`
- Remaining blockers: none
