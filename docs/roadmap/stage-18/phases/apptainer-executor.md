# Phase 3 Execution Plan: Direct Apptainer And Singularity Execution

## Metadata

- Status: pr_open
- Feature focus: HPC Container Execution
- PR title: `HPC Container Execution - Phase 3: Apptainer Executor`
- Branch: `codex/apptainer-executor`
- Worktree: `/home/samcantrill/work/loom-worktrees/apptainer-executor`
- Phase execution plan path: `docs/roadmap/stage-18/phases/apptainer-executor.md`
- Full plan: `docs/roadmap/stage-18/implementation-plan.md`
- Source phase: Stage 18 Phase 3, `apptainer-executor`
- Stack predecessor: none
- Base branch: `origin/develop` at `d88389d`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/184
- Merge eligibility: root phase; merge to `develop` after validation and automated review
- Workflow path: expanded path
- Successor dependency notes: Phase 4 depends on the Apptainer command builder for SLURM wrapping.
- Plan quality gate: passed in the implementation plan on 2026-05-17
- Draft pass: completed by manager before implementation
- Refine pass: completed in this planning pass because this phase adds a new public executor
- Blockers: none

## Objective

Add direct local Apptainer/Singularity execution for prepared stage attempts while preserving Loom's parent-owned worker/result contract. The executor should build deterministic `apptainer exec`/`singularity exec` argv from existing container options, launch through a fakeable adapter-local runner, read the normal stage-worker result from the run store, and report launch/process/worker conflicts as structured execution failures.

## In-Scope Work

- Add Apptainer exec options, command/result records, command runner protocol, fake runner, and subprocess runner under `src/loom/pipeline/executors/apptainer/`.
- Add deterministic exec argv construction with image/SIF ref, bind mounts, workdir, `--cleanenv` by default, explicit environment projection, GPU flags, and selected command identity.
- Add `ApptainerExecutor`/Singularity-compatible execution that mirrors subprocess/Docker prepared-worker result handling.
- Reuse Stage 17 shared container records for container image, mounts, environment, path parity, and redacted metadata.
- Preserve descriptor claims already introduced for `apptainer` and `singularity`; adjust details only if implementation evidence requires it.
- Add unit, contract, integration, and package coverage for command construction, redaction, runtime alias behavior, fake-runner success/failure, worker result parity, and import boundaries.

## Out-of-Scope Work

- SLURM script composition, live submission, build-before-render ordering, or new scheduler executors.
- Whole-controller-in-container mode, MPI/rank orchestration, path translation, site modules, or security sandbox claims.
- Real Apptainer/Singularity runtime requirements in default validation.
- Build policy or build service changes beyond consuming resolved image/SIF refs.

## Assumptions

- Direct Apptainer execution can use existing `adapter_options.container` for image/SIF, mounts, workdir, environment, and path-parity checks.
- `adapter_options.apptainer.command` selects the concrete command; `singularity` executor defaults the command to `singularity`.
- Clean environment is the default unless explicitly disabled.
- GPU exposure is an explicit command flag choice; host driver availability and scheduler allocation stay external.

## Design Impact

- Maintainability: direct executor logic follows existing subprocess/Docker result-handling patterns instead of creating a second worker protocol.
- Extensibility: Phase 4 can reuse command construction for SLURM wrapping without depending on executor internals.
- Domain neutrality: executor invokes configured workers inside user-selected images/SIFs and does not generate project environments.
- Source-tree boundaries: Apptainer command behavior stays adapter-local; shared container records remain runtime-neutral.

## Future Compatibility

- Stage 19 can classify launch, process, worker, timeout-capability, and container runtime facts from executor metadata.
- Stage 20 can project selected command, image/SIF, bind, environment-key, and process facts into runtime events.
- Stage 21 can reason about bind-mounted roots and log references without treating container images as authority state.
- Future path translation or MPI support can extend options explicitly without changing the prepared-worker result contract.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reuse Docker executor code through inheritance | Docker and Apptainer command semantics differ; copying the existing prepared-worker pattern is clearer and easier to review. |
| Put Apptainer flags in shared container records | Would pollute runtime-neutral records with adapter-specific behavior. |
| Add SLURM wrapping now | Scheduler composition is Phase 4 and needs its own review boundary. |
| Disable clean environment by default | Planning selected clean environment defaults to reduce leakage. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Apptainer command/result records remain separate from build records | Avoids large Phase 3 refactor of Phase 2 build helpers | Phase 4 or later shows substantial duplication worth extracting. |
| Direct executor does not enforce CPU/memory resources | Direct Apptainer cannot allocate scheduler resources locally | A site-level local resource enforcement policy is designed. |
| No path translation | Planning selected fail-closed path parity | Remote stores or non-shared filesystems require explicit mapping. |

## Reviewability

- Expected PR size and shape: medium-large executor PR touching Apptainer command/executor modules, exports, tests, and phase metadata.
- Files and areas to inspect: argv construction, redaction, environment projection, path parity, launch/process/worker failure handling, executor metadata, and import boundaries.
- Scope-control checks: no SLURM wrapping, no build commands inside execution, no real runtime tests by default, no path translation, no MPI policy, and no security-sandbox claims.

## Implementation Steps

1. Add Apptainer exec options, command/result records, fake/subprocess runner, and command builder.
2. Add direct executor setup that parses `container` and `apptainer`/`singularity` namespaces, injects required run/artifact mounts, validates path parity, and builds the prepared worker command.
3. Mirror subprocess/Docker result handling for launch failure, invalid runner result, missing/invalid worker result, worker failure, process failure, and worker/process conflicts.
4. Export the new executor/command surfaces and add focused unit/contract/integration/package tests.
5. Run targeted suites, full validation, test summary, PR body preparation, and automated review.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package`.
- Required assertions or deferral reason: importing executor package surfaces remains optional-dependency light and does not require Apptainer/Singularity binaries.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/apptainer/`, `tests/unit/loom/pipeline/test_executor_capabilities.py`.
- Required assertions or deferral reason: argv construction, option validation, redaction, environment projection, GPU flags, alias defaults, fake-runner success/failure, and descriptor claims.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_executor_contract.py`, `tests/contracts/test_executor_capabilities_contract.py`.
- Required assertions or deferral reason: executor contract remains prepared-worker compatible and descriptor contract remains stable.

### Integration Suite

- Status: required.
- Expected paths: focused fake-runner direct executor integration tests under `tests/integration/pipeline/`.
- Required assertions or deferral reason: success, worker failure, process failure, launch failure, missing/invalid worker results, and process/worker conflicts use normal stage result records.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: CLI and SLURM-facing examples are later phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: real Apptainer/Singularity smoke.
- Required assertions or deferral reason: real runtime smoke remains optional Phase 5 work.

## Risks

- Raw environment values leak into metadata or failure details.
- Runtime alias behavior diverges between `apptainer` and `singularity`.
- Direct executor overclaims resource enforcement.
- Setup logic misses required run/artifact mounts or weakens path parity.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/apptainer tests/unit/loom/pipeline/test_executor_capabilities.py
uv run pytest tests/contracts/test_executor_contract.py tests/contracts/test_executor_capabilities_contract.py
uv run pytest tests/integration/pipeline/test_apptainer_executor.py tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes

- Safe implementation slices: command/options first, executor setup/result handling second, integration/package coverage last.
- Tests to run with each slice: command unit tests after argv work, executor unit tests after result handling, integration/package tests after exports.
- Decisions not to revisit: clean environment default, path parity fail-closed, adapter-local command runner, no SLURM composition, no real runtime default tests.
- Stop conditions: direct execution requires path translation, default tests require real Apptainer/Singularity, or environment projection cannot stay redaction-safe.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: used by manager automated review; final target/check verification
  remains before merge
- Blocker resolution: 1/3 used for required host environment projection

## Completion Notes

- Draft plan: completed by manager in this file before code changes.
- Final phase execution plan: refined in this planning pass; ready for implementation.
- Implementation summary: added `ApptainerExecOptions`, deterministic
  `apptainer exec`/`singularity exec` command construction, fake/subprocess
  exec runners, direct `ApptainerExecutor` and `SingularityExecutor`
  prepared-worker execution, CLI/top-level executor selection, selected-command
  metadata, redacted environment projection, path-parity bind injection,
  resource-intent metadata, package import-boundary coverage, and fake-runner
  integration coverage. SLURM composition, docs/preflight, and real runtime
  smoke remain later phases.
- Implementation validation:
  - Focused Apptainer unit suite passed:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/apptainer -q`:
    28 passed.
  - Targeted package/unit/contract suite passed:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/apptainer tests/unit/loom/pipeline/test_executor_capabilities.py tests/contracts/test_executor_contract.py tests/contracts/test_executor_capabilities_contract.py tests/package -q`:
    159 passed, 1 skipped.
  - Integration slice passed outside the sandbox:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_apptainer_executor.py -q`:
    2 passed. The same integration tests cannot start the local authority
    service in the sandbox because socket creation is blocked.
  - Targeted Ruff and Pyright passed for touched implementation and test
    files.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed outside the sandbox:
    Ruff passed; Pyright passed; default harness passed with 1859 passed, 26
    skipped, 18 deselected; config-extra harness passed with 447 passed, 1896
    deselected; `uv build` produced the source distribution and wheel.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed outside the sandbox
    and wrote `build/test-summary.md`; overall summary: 2334 passed, 18
    skipped, 1912 deselected.
- Refinement summary: no phase refiner pass used; the only validation issue was
  a pytest module-name collision fixed by renaming new Apptainer unit test
  files to unique basenames.
- Manager review summary: required host environment variables were initially
  projected as Docker-style name-only entries; fixed Apptainer projection to
  resolve selected host values into redacted `--env NAME=value` argv entries
  and fail setup when a required host variable is absent.
- Post-review validation:
  - Focused Apptainer unit suite passed:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/apptainer -q`:
    28 passed.
  - Targeted Ruff passed for touched implementation and test files.
  - Targeted Pyright passed for touched implementation and test files.
- PR preparation: PR #184 opened against `develop` with body drafted in
  `docs/roadmap/stage-18/phases/apptainer-executor-pr-body.md`.
- Stack maintenance: root phase from `develop`
- Remaining blockers: none
