# Phase 4 Execution Plan: Docker Preflight Diagnostics

## Metadata

- Status: in progress
- Feature focus: Docker Container Executor
- PR title: `Docker Container Executor - Phase 4: Preflight Diagnostics`
- Branch: `codex/docker-preflight-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/docker-preflight-diagnostics`
- Phase execution plan path: `docs/roadmap/stage-17/phases/docker-preflight-diagnostics.md`
- Full plan: `docs/roadmap/stage-17/implementation-plan.md`
- Source phase: Stage 17 Phase 4, `docker-preflight-diagnostics`
- Stack predecessor: none; Phase 3 is merged
- Base branch: `develop`
- Target branch: `develop`
- PR: pending
- Merge eligibility: eligible after implementation, validation, PR
  preparation, GitHub CI, and manager automated review
- Workflow path: expanded path
- Successor dependency notes: Phase 5 should start from `develop` after this
  phase merges, unless a GitHub-side blocker requires stacking.
- Plan quality gate: passed in the implementation plan on 2026-05-16 with no blockers
- Draft pass: completed in this planning pass
- Refine pass: completed in this planning pass
- Setup limitations: default checks must stay Docker-daemon-free and
  network-free
- Blockers: none

## Objective

Add cheap Docker selected-executor preflight diagnostics that catch common
command, configuration, filesystem, environment, and resource readiness issues
before the Docker executor launches a prepared worker, without pulling images,
contacting registries, probing networks, or requiring a live Docker daemon in
default validation.

## Full-Plan Context

Phases 1 through 3 established shared container records, Docker command/result
records, and `DockerExecutor` integration through the prepared-worker path.
This phase exposes readiness checks for that behavior through the existing
diagnostics preflight runner. Phase 5 will publish user-facing Docker examples,
preflight examples, failure inspection docs, and optional live Docker smoke
guidance.

Future-phase work that must stay out of this PR includes docs/examples beyond
minimal test fixtures, live daemon smoke requirements, expensive image
inspection, pulls, registry auth, non-Docker container runtime preflight,
retry/timeout policy, runtime events, transaction policy, and cleanup behavior.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 3 merged to `develop`.
- Why this base branch is correct: Phase 4 depends on the merged container
  records, Docker command layer, and Docker executor integration.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: no successor branch currently depends on
  `codex/docker-preflight-diagnostics`; delete it after merge unless Phase 5 is
  stacked on it because of a GitHub-side blocker.

## Source Phase Summary

- Goal: add cheap selected-executor Docker diagnostics that catch common
  runtime, filesystem, environment, and resource issues before launch.
- Required scope: stable Docker check IDs, selected-executor behavior, redacted
  structured JSON details, and daemon-free readiness checks for command,
  config, mounts, run directory, artifact root, required host env, CPU/memory,
  and unsupported GPU resources.
- Required checkpoints: stable check IDs in the diagnostics model, checks only
  when Docker is selected, shared container record reuse, no raw env values in
  details, no image pulls or daemon-heavy operations, and local/subprocess/SLURM
  regressions.
- Acceptance criteria: Docker preflight reports actionable pass/fail
  diagnostics through existing `PreflightResult` JSON shape and default
  validation remains Docker-free.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/diagnostics/models.py` owns `STABLE_CHECK_IDS`.
  - `src/loom/diagnostics/preflight.py` owns selected group dispatch,
    selected-executor checks, filesystem probes, and stable ID enforcement.
  - `src/loom/pipeline/executors/containers.py` owns image, mount,
    environment, resource intent, redaction, and path-parity summaries.
  - `src/loom/pipeline/executors/docker/commands.py` owns `DockerOptions` and
    command availability semantics.
  - `src/loom/pipeline/executors/docker/executor.py` adds required writable
    run-directory and artifact-root path-parity mounts at execution time.
- Existing tests or harness behavior:
  - `tests/contracts/test_diagnostics_preflight_contract.py` asserts the full
    stable check ID map.
  - `tests/unit/loom/diagnostics/test_diagnostics_preflight.py` already tests
    selected executor checks for local, subprocess, and SLURM.
  - `tests/integration/diagnostics/test_diagnostics_preflight_integration.py`
    verifies default preflight writes no run documents.
- Import-boundary or dependency constraints:
  - Diagnostics may import Docker command/container record modules only on the
    selected Docker path.
  - No Docker SDK, registry, network, image pull, or live daemon dependency may
    appear in default preflight.

## In-Scope Work

- Add Docker preflight check IDs under existing groups:
  - `executor.docker.command`
  - `executor.docker.container_options`
  - `executor.docker.image`
  - `executor.docker.environment`
  - `filesystem.docker.mount_sources`
  - `filesystem.docker.mount_targets`
  - `filesystem.docker.run_dir_writable`
  - `filesystem.docker.artifact_root_visible`
  - `resources.docker.mapping`
  - `resources.docker.gpu`
- Run Docker-specific checks only when `RunOptions.executor` selects `docker`
  or the request runtime mapping explicitly selects Docker.
- Parse `adapter_options.container` and `adapter_options.docker` through the
  Phase 1 and Phase 2 records.
- Check Docker command availability with `shutil.which` only.
- Check image reference presence and redacted container option summaries.
- Check authored mount source existence, target path validity, and Stage 17
  path-parity summaries.
- Check local run-directory parent writability and local artifact-root path
  visibility without creating run documents.
- Check required host environment variable presence by name only.
- Check CPU/memory resource mapping and fail unsupported GPU resource requests
  with structured diagnostics.
- Add unit, contract, integration, and package/import-boundary coverage.

## Out-of-Scope Work

- Expensive image availability, digest, pull, registry, daemon, or network
  probes.
- Docker daemon smoke tests as default validation.
- Non-Docker container runtime preflight.
- New CLI presentation or preflight output schema versions.
- Docker docs and examples beyond fixtures required for tests.
- Reliability, event, transaction, cleanup, or retry policy.

## Assumptions

- Cheap Docker readiness is useful even when it cannot prove image runtime
  availability.
- `shutil.which` is sufficient command availability evidence for Phase 4.
- Path parity remains the Stage 17 filesystem model.
- Existing `resources.capabilities` already reports unsupported GPU at the
  descriptor level; `resources.docker.gpu` adds Docker-specific actionability.
- Default preflight should skip Docker checks for local, subprocess, and SLURM.

## Scope Contract

Stable check IDs added by this phase:

- Executor group:
  - `executor.docker.command`: pass/fail Docker CLI command presence on PATH.
  - `executor.docker.container_options`: pass/fail shared container and Docker
    adapter option parsing, with redacted option-key summaries only.
  - `executor.docker.image`: pass/fail authored image reference presence.
  - `executor.docker.environment`: pass/fail required host environment
    variable availability by name only.
- Filesystem group:
  - `filesystem.docker.mount_sources`: pass/fail authored mount source
    existence and directory/file availability.
  - `filesystem.docker.mount_targets`: pass/fail container target path and
    Stage 17 path-parity summaries.
  - `filesystem.docker.run_dir_writable`: pass/skip/fail local run-directory
    parent writability for a selected run URI.
  - `filesystem.docker.artifact_root_visible`: pass/skip/fail local artifact
    root path visibility and required path-parity mount shape.
- Resources group:
  - `resources.docker.mapping`: pass/warn/fail CPU and memory capability and
    Docker flag mapping readiness.
  - `resources.docker.gpu`: pass/fail when GPU resources are absent or present.

Details must be plain data, deterministic, actionable, and redaction-safe.
Environment variable values must never be included. Docker checks may summarize
variable names, required host variable names, option keys, image reference,
paths, capability levels, and boolean probe facts.

## Design Impact

- Maintainability: checks stay inside the existing preflight dispatch and reuse
  shared container/Docker records instead of introducing a diagnostics-specific
  Docker parser.
- Extensibility: Stage 18 can mirror the selected-executor check pattern for
  other container runtimes while reusing the generic container summaries.
- Domain neutrality: messages describe generic command, filesystem, and
  resource readiness.
- Source-tree boundaries: diagnostics consumes executor-owned summaries but
  does not own Docker command construction or executor lifecycle.

## Future Compatibility

- Stage 18 can add Apptainer/Singularity check IDs beside these Docker IDs.
- Stage 19 can consume Docker process/failure facts without changing preflight
  contracts.
- Stage 20 can project the same structured readiness facts into event surfaces
  if needed.
- Stage 21 cleanup work remains independent because preflight creates no run
  documents or container resources.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Run `docker version` or `docker image inspect` by default | Can require a daemon and may be slower or environment-dependent. |
| Put Docker diagnostics in a new preflight group | Existing executor/resources/filesystem groups already cover the readiness axes and preserve CLI schema. |
| Report raw adapter payloads for debugging | Would violate redaction and persistence constraints. |
| Treat missing run URI as Docker filesystem failure | Existing preflight uses skips for run-path-dependent checks without a run URI. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Command readiness only checks PATH, not daemon health | Keeps default preflight cheap and Docker-free | A future opt-in expensive preflight mode is approved. |
| Artifact-root visibility is local-run-store specific | Stage 17 Docker executor requires local path parity | Remote store or path-translation work lands. |
| Docker resource mapping duplicates some capability facts | Provides Docker-specific user guidance | A shared container resource preflight layer is introduced. |

## Reviewability

- Expected PR size and shape: medium diagnostics PR touching models,
  preflight checks, and focused diagnostics/package tests.
- Files and areas to inspect: stable check ID map, selected-Docker gating,
  redaction in details, filesystem probes, resource mapping, and no daemon or
  network calls.
- Scope-control checks: no docs/examples phase work, no Docker SDK, no image
  pulls, no live daemon probes, and no changes to CLI output schema.

## Implementation Steps

1. Add Docker check IDs to `STABLE_CHECK_IDS` and contract expectations.
2. Add small helper functions in `diagnostics.preflight` to detect selected
   Docker runtime options and parse redacted Docker/container summaries.
3. Implement Docker executor checks for command availability, option shape, and
   image reference presence.
4. Implement Docker filesystem checks for mount sources, mount targets,
   run-directory writability, and local artifact-root visibility.
5. Implement Docker resource checks for CPU/memory mapping and unsupported GPU.
6. Add tests for pass/fail/skip cases, selected-executor behavior, JSON
   serialization, redaction, and non-Docker regressions.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: default preflight and CLI preflight
  remain import-light and do not import Docker SDKs or daemon-facing modules by
  default.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`,
  `tests/unit/loom/diagnostics/test_diagnostics_models.py`.
- Required assertions or deferral reason: missing Docker command, invalid or
  missing container options, missing image, invalid mount source/target,
  run-directory writability, artifact-root visibility, missing required env,
  CPU/memory mapping, GPU unsupported, redaction, and selected-executor
  behavior.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_diagnostics_preflight_contract.py`,
  `tests/contracts/test_cli_preflight_contract.py`.
- Required assertions or deferral reason: stable check IDs include Docker IDs
  and JSON/details remain plain-data compatible without schema-version changes.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/diagnostics/test_diagnostics_preflight_integration.py`,
  `tests/integration/diagnostics/test_cli_preflight.py`.
- Required assertions or deferral reason: Docker-selected preflight emits
  expected checks without writing run documents or requiring Docker, and CLI
  JSON includes redaction-safe Docker diagnostics.

### E2E Suite

- Status: deferred.
- Expected paths: none required for this phase.
- Required assertions or deferral reason: end-to-end Docker examples and
  optional live smoke belong to Phase 5.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: live Docker daemon smoke remains
  optional Phase 5 work.

## Risks

- Accidentally adding a daemon or network dependency to default preflight.
- Leaking raw environment values in diagnostic details.
- Letting check IDs drift from the contract test map.
- Duplicating executor mount behavior incorrectly and allowing execution-time
  failures that preflight should catch.
- Breaking local, subprocess, or SLURM selected-executor preflight output.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/contracts/test_diagnostics_preflight_contract.py
uv run pytest tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/integration/diagnostics/test_cli_preflight.py
uv run pytest tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
uv run pytest tests/unit/loom/diagnostics tests/contracts tests/integration tests/package
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: unused; one pass available if validation
  fails, check IDs are unstable, or diagnostics leak raw data.
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this planning pass.
- Final phase execution plan: refined in this planning pass; no open planning
  blockers.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
