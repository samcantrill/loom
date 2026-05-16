# Phase 2 Execution Plan: Docker Command Builder And Runner

## Metadata

- Status: in_progress
- Feature focus: Docker Container Executor
- PR title: `Docker Container Executor - Phase 2: Command Builder And Runner`
- Branch: `codex/docker-command-runner`
- Worktree: `/home/samcantrill/work/loom-worktrees/docker-command-runner`
- Phase execution plan path: `docs/roadmap/stage-17/phases/docker-command-runner.md`
- Full plan: `docs/roadmap/stage-17/implementation-plan.md`
- Source phase: Stage 17 Phase 2, `docker-command-runner`
- Stack predecessor: none; Phase 1 is merged
- Base branch: `develop`
- Target branch: `develop`
- PR: pending
- Merge eligibility: root phase, eligible to merge to `develop` after implementation, validation, PR preparation, and automated review pass
- Workflow path: expanded path
- Plan quality gate: passed in the implementation plan on 2026-05-16 with no blockers
- Draft pass: completed in this planning pass
- Refine pass: completed in this planning pass
- Blockers: none

## Objective

Add the Docker-local command and process contract that later executor
integration will consume. This phase builds deterministic `docker run` argv
records, redacted command projections, bounded process-result records, a
fakeable runner protocol, subprocess-backed runner, and cheap Docker metadata
helpers without executing Loom stages through Docker yet.

## Full-Plan Context

Phase 1 added shared container records and the Docker runtime descriptor.
Phase 2 consumes those shared records to create Docker-specific command
behavior. Phase 3 will wire this command layer into `DockerExecutor`; Phase 4
will use the command/metadata helpers in preflight diagnostics; Phase 5 will
publish examples and optional live Docker acceptance.

Future-phase work that must stay out of this PR includes executor lifecycle
integration, CLI `--executor docker` selection, worker-result interpretation,
preflight check IDs/presentation, image pulls, registry authentication, Docker
Compose, Kubernetes, and live Docker requirements in default validation.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 merged to `develop`.
- Why this base branch is correct: Phase 2 depends on the merged Phase 1 shared
  container records and descriptor/config shape.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: do not delete `codex/docker-command-runner` while
  any successor phase branches depend on it.

## Source Phase Summary

- Goal: build deterministic, shell-free, redaction-safe Docker CLI invocations
  and fakeable process-result handling without parent runner finalization.
- Required scope: Docker-specific option records, `docker run` argv builder,
  bounded command/result records, `DockerCommandRunner` protocol,
  subprocess-backed and fake runners, daemon-free version/digest helpers, and
  focused package/unit/contract tests.
- Required checkpoints: final Docker option names, output bounds,
  resource-flag mapping, redacted command projection, and no Docker SDK or
  registry/network behavior.
- Acceptance criteria: deterministic argv, no shell interpolation, validated
  mounts/env/resources only, no raw env values in redacted projections, bounded
  stdout/stderr/error facts, fake-runner tests exercising the same protocol,
  and no default Docker daemon dependency.

## In-Scope Work

- Add `loom.pipeline.executors.docker` package and command-owned records.
- Define `DockerOptions` for Docker-owned adapter options that are safe for
  deterministic command construction.
- Define `DockerRunCommand` with full argv plus redacted argv and metadata
  projections.
- Build `docker run` argv from `ContainerOptions`, `DockerOptions`, and a
  prepared worker command sequence.
- Map generic container fields to Docker flags:
  - image reference becomes the image argument before the worker command;
  - workdir becomes `--workdir`;
  - mounts become deterministic `--mount type=bind,source=...,target=...,readonly`
    entries;
  - explicit environment values become `--env NAME=value`;
  - required host variables become `--env NAME`;
  - CPU resources become `--cpus`;
  - memory resources become `--memory`;
  - GPU resources remain unsupported and fail closed.
- Bound command stdout/stderr and process error text at
  `MAX_DOCKER_COMMAND_OUTPUT_CHARS = 4096`.
- Provide `DockerCommandResult`, `DockerCommandRunner`,
  `SubprocessDockerCommandRunner`, and `FakeDockerCommandRunner`.
- Provide cheap version and local image digest helpers that use the same runner
  protocol and do not pull images or contact registries by default.
- Add package, unit, and contract tests for command shape, result
  serialization, redaction, resource flags, fake runner behavior, subprocess
  exception mapping, bounded output, and import boundaries.

## Out-of-Scope Work

- `DockerExecutor` and parent runner lifecycle integration.
- CLI executor selection.
- Stable preflight check IDs or diagnostics presentation.
- Worker-result reading, failure mapping, or finalization.
- Live Docker requirements in default validation.
- Docker SDK, registry auth, image pulls, build commands, Compose, Kubernetes,
  GPU mapping, or path translation.

## Assumptions

- Authored Docker options are trusted project config, but raw environment
  values and process outputs must be bounded/redacted before durable metadata.
- The command builder can prove correctness using fake runner tests only.
- Stage 17 uses path parity; command construction should not introduce host to
  container path translation.
- Docker CPU and memory flags are best-effort projections of Phase 1 resource
  intent; unsupported GPU requests fail before command execution.

## Scope Contract

Public command record and helper names for this phase:

- `DockerOptionError`: raised for Docker-specific option or command errors.
- `DockerOptions`: Docker-owned adapter options with deterministic plain-data
  shape:
  `{command: str, remove: bool, network: str | None, platform: str | None, user: str | None, hostname: str | None}`.
  The default command is `docker`, `remove` defaults to true, and optional
  text fields reject empty/control-character values.
- `DockerRunCommand`: `{argv: list[str], redacted_argv: list[str], metadata: Mapping[str, PlainData]}`.
  `argv` is the exact shell-free command. `redacted_argv` and metadata redact
  explicit environment values before persistence.
- `DockerCommandResult`: versioned plain-data record with
  `{schema_version, command, argv, redacted_argv, returncode, stdout, stderr, started_at, finished_at, timed_out, timeout_seconds, error}`.
  Output and error text are sanitized and bounded.
- `DockerCommandRunner`: protocol with `require`, `run`, `version`, and
  `image_digest` methods.
- `SubprocessDockerCommandRunner`: subprocess-backed implementation using
  `subprocess.run(..., shell=False, capture_output=True, text=True)`.
- `FakeDockerCommandRunner`: deterministic test runner that records calls and
  can script results or command unavailability.

Error behavior and edge cases:

- Reject non-sequence or empty worker commands, non-string argv entries, empty
  Docker command names, control characters in argv/options, unsupported mount
  modes, unsupported GPU resource requests, unsupported resource kinds, and
  malformed result payloads.
- Explicit `--env NAME=value` values must be redacted in `redacted_argv` and
  metadata; required host variables remain as names only.
- Output bounding must preserve artifact-safe text and indicate truncation via
  the bounded suffix.
- Version/digest helpers must return bounded process results and never pull
  images or inspect registries by default.

## Design Impact

- Maintainability: Docker command behavior is isolated in a Docker-owned module
  and consumes Phase 1 container records instead of reparsing raw dictionaries.
- Extensibility: Stage 18 can reuse the fakeable command-runner pattern and
  bounded result records without inheriting Docker flags.
- Domain neutrality: tests use generic image and stage-worker command fixtures.
- Source-tree boundaries: command construction remains executor-owned; runtime,
  diagnostics, CLI, stores, and execution lifecycle remain consumers in later
  phases.

## Future Compatibility

- Stage 3 can wire `DockerCommandRunner` into `DockerExecutor` without changing
  the public command/result records.
- Stage 4 can use `require`, `version`, and path/resource validation helpers
  for cheap selected-executor preflight without adding Docker daemon defaults.
- Stage 19 can consume bounded process facts for retry, timeout, and
  failure-category policy later.
- Stage 20 can project redacted command metadata into runtime events.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Build Docker commands as shell strings | Shell interpolation makes redaction, quoting, and test assertions less reliable. |
| Put Docker command flags in the shared `container` namespace | Would leak Docker-specific behavior into Stage 18 shared records. |
| Use Docker SDK or daemon inspection now | Violates no-SDK/default-daemon-free constraints and broadens dependencies. |
| Allow arbitrary Docker flag passthrough in Phase 2 | Makes deterministic command validation and redaction harder; add concrete flags when needed. |
| Implement executor lifecycle with the command builder | Phase 3 owns worker-result and finalization semantics. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Docker-specific option record is intentionally small | Keeps Phase 2 reviewable and avoids passthrough redaction gaps | A later phase needs a concrete Docker flag with tests. |
| Image digest helper is local/cheap only | Avoids registry/network behavior in default tests | Release acceptance requires image lock or registry provenance. |
| CPU/memory mapping is best effort | Docker platform behavior varies | Maintainers define stricter resource enforcement policy. |

## Reviewability

- Expected PR size and shape: medium command-layer PR adding a Docker package,
  command/result records, runners, and focused tests.
- Files and areas to inspect: argv ordering, environment redaction, output
  bounds, resource flag mapping, fake/subprocess runner parity, and absence of
  executor lifecycle or CLI selection.
- Scope-control checks: no `DockerExecutor`, no CLI selection, no preflight
  check IDs, no Docker SDK, no shell-string command execution, no live Docker
  default tests.

## Implementation Steps

1. Add the Docker package and command/error/result option records.
2. Implement deterministic `docker run` argv and redacted projections from
   Phase 1 `ContainerOptions`.
3. Implement bounded `DockerCommandResult` and exception/result helpers.
4. Implement the runner protocol, subprocess runner, fake runner, version, and
   digest helpers.
5. Add unit and contract tests for command construction, serialization,
   redaction, resource handling, runner behavior, and import boundaries.
6. Run targeted tests, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py` and adjacent
  package API tests if exports change.
- Required assertions or deferral reason: importing Docker command records must
  not import Docker SDK, diagnostics, CLI, execution lifecycle, network
  libraries, subprocess, or daemon-facing code. Existing `loom.pipeline` parent
  package imports may load store-facing symbols, so Phase 2 does not use that
  as a Docker-specific failure signal.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/docker/test_commands.py`
  and existing executor tests as needed.
- Required assertions or deferral reason: valid/invalid Docker options,
  deterministic argv, mount/workdir/env/resource flags, redacted argv,
  bounded outputs, fake-runner calls, subprocess exception mapping,
  version/digest helper behavior, and unsupported GPU errors.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_docker_command_contract.py`.
- Required assertions or deferral reason: stable plain-data command/result
  shapes, result round trips, redacted metadata shape, and no raw environment
  values in persistence-facing projections.

### Integration Suite

- Status: deferred for this phase.
- Expected paths: none required before Phase 3.
- Required assertions or deferral reason: this phase does not execute stage
  attempts through Docker or read worker results.

### E2E Suite

- Status: deferred for this phase.
- Expected paths: none.
- Required assertions or deferral reason: CLI `--executor docker` selection is
  Phase 3 work.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: live Docker smoke remains optional
  Phase 5 work.

## Risks

- Raw environment values leak through redacted argv or metadata.
- The command builder accepts arbitrary flags before concrete redaction rules
  exist.
- Process result output grows unbounded.
- Fake runner diverges from the subprocess-backed protocol.
- Docker command code imports execution lifecycle, CLI, diagnostics,
  subprocess at import time, network libraries, or optional Docker SDK modules.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/docker/test_commands.py
uv run pytest tests/contracts/test_docker_command_contract.py
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_executor_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in this planning pass.
- Final phase execution plan: refined in this planning pass; no open planning
  blockers.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance: root phase from `develop`; no predecessor.
- Remaining blockers: none.
