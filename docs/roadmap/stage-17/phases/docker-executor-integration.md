# Phase 3 Execution Plan: Docker Executor Integration

## Metadata

- Status: pr_open
- Feature focus: Docker Container Executor
- PR title: `Docker Container Executor - Phase 3: Executor Integration`
- Branch: `codex/docker-executor-integration`
- Worktree: `/home/samcantrill/work/loom-worktrees/docker-executor-integration`
- Phase execution plan path: `docs/roadmap/stage-17/phases/docker-executor-integration.md`
- Full plan: `docs/roadmap/stage-17/implementation-plan.md`
- Source phase: Stage 17 Phase 3, `docker-executor-integration`
- Stack predecessor: none; Phase 2 is merged
- Base branch: `develop`
- Target branch: `develop`
- PR: [#173](https://github.com/samcantrill/loom/pull/173)
- Merge eligibility: root phase, eligible to merge to `develop` after implementation, validation, PR preparation, and automated review pass
- Workflow path: expanded path
- Plan quality gate: passed in the implementation plan on 2026-05-16 with no blockers
- Draft pass: completed in this planning pass
- Refine pass: completed in this planning pass
- Blockers: none

## Objective

Wire the Phase 1 container records and Phase 2 Docker command layer into a real
prepared-worker `DockerExecutor`. The executor should launch one prepared stage
worker through Docker, read the standard worker result from the run store, and
return a `StageExecutionResult` while leaving finalization, artifact indexes,
status authority, and run-store commits with the parent runner.

## Full-Plan Context

Phase 1 established shared container records and the Docker descriptor. Phase 2
added Docker command/result records and fakeable runners. Phase 3 is the first
phase that makes `loom run --executor docker` execute stages through the normal
prepared-worker path. Phase 4 adds selected-executor preflight diagnostics.
Phase 5 publishes examples and optional live Docker smoke guidance.

Future-phase work that must stay out of this PR includes Docker preflight check
IDs/presentation, broad retry/timeout policy, Docker-specific CLI command
groups, image pulls, registry auth, Compose/Kubernetes, Stage 18 runtimes, and
live Docker requirements in default validation.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 2 merged to `develop`.
- Why this base branch is correct: Phase 3 depends on merged Phase 1 records
  and Phase 2 command-runner contracts.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: do not delete `codex/docker-executor-integration`
  while any successor phase branches depend on it.

## Source Phase Summary

- Goal: run prepared stage attempts through Docker while preserving existing
  runner, worker-result, run-store, artifact-store, failure, and log semantics.
- Required scope: `DockerExecutor`, lazy executor exports, CLI executor
  selection, per-attempt option parsing/path-parity mounts, Docker process
  launch, worker-result normalization, failure mapping, redacted metadata, and
  fake-runner unit/integration/CLI tests.
- Required checkpoints: executor metadata shape, process/failure detail fields,
  parent-owned finalization, fake pipeline execution, and local/subprocess/SLURM
  selection regressions.
- Acceptance criteria: `loom run --executor docker` can complete a small
  fake-runner pipeline, Docker failures are mapped to existing execution
  failure semantics, raw env values stay out of metadata, and no Docker daemon
  is required by default tests.

## In-Scope Work

- Add `DockerExecutor` under `loom.pipeline.executors.docker`.
- Mark it `requires_prepared_worker_request = True`.
- Parse `adapter_options.container` and `adapter_options.docker` from
  `StageExecutionRequest.resolved_runtime`.
- Derive container resource intent from resolved runtime resources and the
  Docker descriptor capabilities.
- Add path-parity mounts for the local run directory and local artifact root
  when they are not already mounted.
- Build the existing durable stage-worker command with authority config support
  and run it through `DockerCommandRunner`.
- Read and validate `StageWorkerResult` exactly like the prepared subprocess
  path: missing, invalid, identity mismatch, failed worker result, cancelled
  worker result, and process/worker conflicts all return structured
  `StageExecutionResult` values.
- Persist redacted executor metadata with Docker command/result facts, path
  summaries, log paths, exit code/signal, timeout facts, and no raw adapter or
  raw environment values.
- Add lazy package export for `DockerExecutor`.
- Wire `loom run --executor docker` through `_build_executor` and supported
  executor messaging.
- Add fake-runner unit/integration/CLI tests and selection regressions.

## Out-of-Scope Work

- Docker preflight check IDs and diagnostics presentation.
- Real Docker daemon validation in default suites.
- Docker-specific CLI command groups.
- Parent-owned finalization, artifact-index writes, run-store status authority,
  or transaction policy inside `DockerExecutor`.
- Image pulls, registry auth, Compose, Kubernetes, GPU mapping, path
  translation, or Stage 18 runtimes.

## Assumptions

- The existing prepared-worker request/result contract is sufficient for Docker.
- The container image contains a usable `python` command by default; constructor
  injection can override it for tests or specialized images.
- Path parity remains the only Stage 17 mount strategy.
- Default validation proves behavior with fake Docker runners and does not need
  a Docker daemon.

## Scope Contract

Executor names and metadata fields:

- `DockerExecutor.name = "docker"`.
- `DockerExecutor.requires_prepared_worker_request = True`.
- Constructor parameters: `run_store`, optional `docker_command_runner`,
  optional `python_executable`, and optional `clock`.
- Executor metadata shape:
  - `executor`: `"docker"`;
  - `command`: redacted Docker argv;
  - `worker_command`: prepared worker command argv;
  - `container`: `ContainerOptions.to_redacted_metadata()`;
  - `path_parity`: list of path-parity summaries;
  - `returncode`, `exit_code`, `signal`, `timed_out`, `timeout_seconds`,
    `stdout`, `stderr`, and `error` from bounded `DockerCommandResult` facts;
  - `docker`: version/digest fields are not required in Phase 3 unless already
    available from the command result.
- Failure detail fields:
  - `launch_error` for runner or command setup exceptions;
  - `result` plus `error` for missing/invalid worker result;
  - `result_run_uri`, `result_stage`, or `result_attempt` for identity
    mismatch;
  - `worker_status` and nested `worker_failure` for failed/cancelled worker
    results or process/worker conflicts.

Error behavior and edge cases:

- Invalid container/Docker options produce an executor-infrastructure failure,
  not a parent-runner exception.
- Nonzero Docker process with missing worker result maps to a Docker process
  failure with exit code or signal.
- Worker success plus nonzero Docker process is a process/worker conflict.
- Worker failure plus zero Docker process is a process/worker conflict.
- Worker failure plus nonzero Docker process returns the worker failure wrapped
  with Docker process metadata.
- Cancelled worker result is propagated as `StageStatus.CANCELLED` unless the
  Docker process also failed.

## Design Impact

- Maintainability: Docker lifecycle code mirrors subprocess prepared-worker
  behavior while using the Docker-local command layer for backend specifics.
- Extensibility: Stage 18 can copy the prepared-worker executor pattern for
  other container runtimes without changing runner semantics.
- Domain neutrality: tests use generic stage fixtures and fake Docker runners.
- Source-tree boundaries: executor code returns results only; parent runner
  retains finalization, artifact index, run status, and lifecycle authority.

## Future Compatibility

- Phase 4 can consume executor metadata and path summaries for selected-executor
  Docker preflight without changing command/executor contracts.
- Stage 19 can wrap Docker process facts with retry/timeout policy later.
- Stage 20 can project Docker command and result metadata into runtime events.
- Stage 21 can consume log/staging facts without Docker owning cleanup.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reimplement parent runner finalization inside `DockerExecutor` | Would duplicate status/artifact authority and conflict with Stage 19/21 assumptions. |
| Run stage objects directly inside Docker | Bypasses the durable prepared-worker contract and current stage-worker CLI. |
| Require live Docker for default tests | Violates daemon-free validation strategy. |
| Add Docker-specific CLI command groups now | Phase 3 only needs executor selection through `loom run`. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Default in-container Python command is `python` | Keeps command construction image-neutral | Phase 5 examples need a different standard invocation. |
| Mount strategy remains path parity only | Matches Stage 17 planning and current local store paths | Stage 18 or remote stores require path translation. |
| Timeout facts are recorded but not policy-owned | Stage 19 owns retry/timeout policy | Shared reliability phase begins. |

## Reviewability

- Expected PR size and shape: medium-to-large executor integration PR touching
  Docker executor code, executor exports, CLI selection, and focused tests.
- Files and areas to inspect: failure mapping, worker-result identity checks,
  metadata redaction, path mount preparation, CLI executor selection, and no
  parent-finalization writes inside `DockerExecutor`.
- Scope-control checks: no preflight check IDs, no Docker daemon tests, no SDK,
  no registry/image pulls, no broad CLI command group.

## Implementation Steps

1. Add `DockerExecutor` and shared helper functions for runtime option parsing,
   path mount preparation, worker command construction, and metadata mapping.
2. Reuse or mirror subprocess worker-result validation and conflict handling
   with Docker-specific executor names/messages.
3. Update Docker package exports and executor package lazy exports.
4. Wire CLI `_build_executor` and unsupported-executor messaging for Docker.
5. Add unit tests for success, missing/invalid/mismatched worker results,
   process conflicts, failed/cancelled worker results, launch/setup errors,
   path mounts, and redaction.
6. Add integration/CLI tests for fake-runner pipeline execution and executor
   selection regressions.
7. Run targeted tests, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_executor_api.py`,
  `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: package exports remain lazy and
  importing executor roots does not import Docker SDK or subprocess at import
  time beyond existing package behavior.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/docker/test_executor.py`,
  `tests/unit/loom/cli/test_run.py`.
- Required assertions or deferral reason: executor success/failure/cancel
  mapping, command metadata redaction, mount preparation, resource intent
  derivation, CLI `_build_executor("docker")`, and unsupported messaging.

### Contract Suite

- Status: required via existing executor/command contracts.
- Expected paths: existing `tests/contracts/test_executor_contract.py`,
  `tests/contracts/test_docker_command_contract.py`, and adjacent contracts if
  public record shape changes.
- Required assertions or deferral reason: no new durable schema beyond existing
  `StageExecutionResult`/`ExecutionFailure` and Phase 2 command records.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_docker_executor_integration.py`.
- Required assertions or deferral reason: fake Docker runner completes a small
  prepared-worker pipeline through `PipelineRunner`, parent finalizes outputs,
  and fake Docker command contains prepared worker invocation.

### E2E Suite

- Status: targeted CLI regression required.
- Expected paths: `tests/e2e/test_cli_core.py` or focused adjacent CLI tests.
- Required assertions or deferral reason: `loom run --executor docker` selects
  Docker executor without routing to SLURM or unsupported-executor errors. Full
  live Docker e2e remains Phase 5.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: live Docker smoke remains optional
  Phase 5 work.

## Risks

- Docker executor duplicates parent finalization or store authority behavior.
- Missing path-parity mounts make prepared worker requests invisible in real
  Docker use.
- Failure details or command metadata leak raw environment values.
- CLI selection breaks local, subprocess, or SLURM paths.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/docker/test_executor.py
uv run pytest tests/unit/loom/cli/test_run.py
uv run pytest tests/integration/pipeline/test_docker_executor_integration.py
uv run pytest tests/package/test_pipeline_executor_api.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted tests, file-scoped
  Pyright, Ruff, broad phase validation, and full PR gate passed after local
  implementation fixes.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in this planning pass.
- Final phase execution plan: refined in this planning pass; no open planning
  blockers.
- Implementation summary: added `DockerExecutor` as a prepared-worker executor;
  parsed container/Docker adapter options; derived resource flags from resolved
  runtime resources; added run-dir and artifact-root path-parity mounts; mapped
  Docker command results and worker results into `StageExecutionResult`; kept
  Docker package exports lazy; wired `loom run --executor docker`; and added
  unit, integration, package, and CLI coverage.
- Implementation validation:
  - `uv run pytest tests/unit/loom/pipeline/executors/docker/test_executor.py tests/unit/loom/cli/test_run.py tests/integration/pipeline/test_docker_executor_integration.py tests/package/test_pipeline_executor_api.py tests/package/test_import_boundaries.py`: passed, `87 passed`.
  - `uv run ruff check src/loom/pipeline/executors/docker src/loom/pipeline/executors/__init__.py src/loom/cli/run.py tests/unit/loom/pipeline/executors/docker/test_executor.py tests/unit/loom/cli/test_run.py tests/integration/pipeline/test_docker_executor_integration.py tests/package/test_pipeline_executor_api.py`: passed.
  - `uv run pyright src/loom/pipeline/executors/docker/executor.py tests/unit/loom/pipeline/executors/docker/test_executor.py tests/integration/pipeline/test_docker_executor_integration.py`: passed, `0 errors`.
  - `uv run pytest tests/unit/loom/pipeline/executors tests/integration tests/e2e tests/package`: failed in the no-extra ad hoc environment because optional-dependency diagnostics tests selected config-dependent CLI paths without installing `loom[config]`; reproduced error was `MissingConfigDependencyError` for `omegaconf`/`yaml`.
  - `uv run --extra config pytest tests/unit/loom/pipeline/executors tests/integration tests/e2e tests/package`: passed, `502 passed`.
  - `make validate-pr`: passed; Ruff, Pyright, default harness (`1742 passed, 26 skipped, 18 deselected`), config-extra harness (`440 passed, 1779 deselected`), and build passed.
  - `make test-summary`: passed; package `99 passed, 1 skipped`, unit `1221 passed, 7 skipped, 1 deselected`, contract `250 passed, 2 skipped`, integration `157 passed, 8 skipped, 13 deselected`, e2e `43 passed, 2 deselected`, config-extra `440 passed, 1779 deselected`, overall `2210 passed, 18 skipped, 1795 deselected`.
- Refinement summary: local implementation fixes addressed import-boundary
  eagerness in `loom.pipeline.executors.docker`, empty adapter-option test
  setup, and Pyright `PlainData`/protocol typing before the implementation
  commit; no separate phase-refiner pass was needed.
- Blocker-resolution summary:
- PR preparation: PR body drafted in
  `docs/roadmap/stage-17/phases/docker-executor-integration-pr-body.md`; PR
  [#173](https://github.com/samcantrill/loom/pull/173) opened against verified
  `develop` from `codex/docker-executor-integration`.
- Stack maintenance: root phase from `develop`; no predecessor.
- Remaining blockers: none.
