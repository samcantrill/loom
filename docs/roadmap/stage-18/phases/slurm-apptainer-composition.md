# Phase 4 Execution Plan: SLURM Plus Apptainer Composition

## Metadata

- Status: pr_open
- Feature focus: HPC Container Execution
- PR title: `HPC Container Execution - Phase 4: SLURM Apptainer Composition`
- Branch: `codex/slurm-apptainer-composition`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-apptainer-composition`
- Phase execution plan path: `docs/roadmap/stage-18/phases/slurm-apptainer-composition.md`
- Full plan: `docs/roadmap/stage-18/implementation-plan.md`
- Source phase: Stage 18 Phase 4, `slurm-apptainer-composition`
- Stack predecessor: none
- Base branch: `origin/develop` at `a2d0aa9`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/185
- Merge eligibility: root phase; merge to `develop` after validation, automated review, and GitHub checks
- Workflow path: expanded path
- Successor dependency notes: Phase 5 depends on the resulting user-facing SLURM/Apptainer behavior for docs and preflight.
- Plan quality gate: passed in the implementation plan on 2026-05-17
- Draft pass: completed by manager before implementation
- Refine pass: completed in this planning pass because this phase composes scheduler and container behavior
- Blockers: none

## Objective

Compose the existing SLURM dry-run/live submission paths with resolved Apptainer/Singularity execution without creating a new scheduler executor. Generated scripts should wrap the same prepared-run or stage-job commands in deterministic Apptainer exec argv, and any selected Apptainer build target should resolve before dry-run rendering or live `sbatch`.

## In-Scope Work

- Add an adapter-local SLURM container composition helper that wraps existing `SlurmCommandArgv` records with Phase 3 Apptainer exec command construction.
- Preserve existing single-job and afterok planning modes, manifests, generated script paths, `sbatch`, status, and cancellation behavior.
- Resolve run-level and stage-level `adapter_options.container.target` references from `adapter_options.container_build` before SLURM scripts are rendered.
- Map successful Apptainer SIF output refs into the container image/SIF reference used by the SLURM-wrapped command.
- Fail before dry-run artifact rendering or live submission when selected build targets are missing, fail, or resolve to non-Apptainer outputs.
- Record redacted container command/build summaries in generated command metadata while keeping SLURM resource summaries distinct from Apptainer runtime/device flags.
- Add focused unit, integration, e2e, and contract coverage for command wrapping, target resolution, dry-run rendering, live fake `sbatch`, and existing SLURM regressions.

## Out-of-Scope Work

- New `slurm-apptainer` executor names or a new scheduler backend.
- Docker execution inside SLURM.
- Build commands inside generated batch scripts.
- Site module policy, MPI/rank orchestration, multi-node topology policy, path translation, or security-sandbox claims.
- Real SLURM, Apptainer, Singularity, Docker, registry, network, or fakeroot requirements in default validation.

## Assumptions

- Existing `SlurmCommandArgv` and rendering paths are the right composition point.
- SLURM continues to own resource allocation; Apptainer composition records runtime/device flags and the selected image/SIF only.
- Stage 18 build targets are selected through `adapter_options.container.target`; direct `adapter_options.container.image` remains valid and bypasses build resolution.
- The CLI dry-run/live paths are the integration point for submit-side build ordering; lower-level submit APIs consume already-rendered planning results.

## Design Impact

- Maintainability: composition stays in SLURM/Apptainer boundary helpers and does not duplicate scheduler submission logic.
- Extensibility: future preflight and reliability work can inspect structured command metadata rather than parsing scripts.
- Domain neutrality: build targets and containers remain generic runtime mechanics with no project environment recipes.
- Source-tree boundaries: shared `container_build` records stay runtime-neutral; Apptainer command semantics stay adapter-owned; SLURM keeps scheduler authority.

## Future Compatibility

- Stage 19 can distinguish build-resolution failures, scheduler submission failures, container launch facts, and worker-result failures.
- Stage 20 can project build, container command, and scheduler facts into runtime events without scraping batch scripts.
- Stage 21 can reason about generated scripts, bind roots, and build evidence as cleanup candidates without treating them as authority state.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add `slurm-apptainer` executor names | Planning explicitly keeps existing SLURM executors and composes adapter namespaces. |
| Generate build commands inside batch scripts | Would hide controller-side failures and make dry-run artifacts non-deterministic. |
| Reimplement live submission for containers | Existing `sbatch`, status, cancellation, and manifest paths already own scheduler behavior. |
| Put Apptainer flags into `SlurmOptions` | Would blur scheduler options with container runtime behavior. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Build resolution is integrated first through CLI dry-run/live flows | These are the submit-side paths with runtime config and run-store context | Non-CLI public planning APIs need first-class build target resolution. |
| Script artifacts contain executable container argv | Batch scripts must be runnable by SLURM | A future secret-handoff design supports non-persisted environment materialization. |
| No path translation | Planning selected path parity only | Remote stores or non-shared filesystems require explicit mapping. |

## Reviewability

- Expected PR size and shape: medium scheduler/container composition PR touching SLURM options/planning, a new composition helper, CLI run integration, exports, and focused tests.
- Files and areas to inspect: command wrapping, redacted metadata, target-to-output resolution, build failure mapping, dry-run script output, live fake submission reuse, and resource ownership wording.
- Scope-control checks: no new scheduler backend, no build commands in scripts, no real runtime default tests, no MPI/site module policy, and no broad retry/timeout policy.

## Implementation Steps

1. Add structured `SlurmCommandArgv` metadata and a SLURM/Apptainer command wrapper over `build_apptainer_exec_command`.
2. Add container target resolution helpers that parse `container_build`, build only selected Apptainer targets, validate output refs, and return resolved `container.image` payloads plus redacted build summaries.
3. Thread optional container wrapping into single-job and afterok SLURM planning while preserving existing script/artifact paths.
4. Integrate build resolution and container wrapping in CLI dry-run and live submission before rendering/submission.
5. Add focused unit, integration, e2e, contract/package coverage and run the phase validation gates.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package`.
- Required assertions or deferral reason: public imports remain optional-runtime light and do not require real SLURM/Apptainer binaries.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/`, `tests/unit/loom/cli/test_run.py`.
- Required assertions or deferral reason: command wrapping, metadata round trips, container target resolution, build failure mapping, and CLI runtime-option rewriting.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_slurm_manifest_contract.py`, `tests/contracts/test_container_executor_contract.py`.
- Required assertions or deferral reason: manifest command metadata remains plain-data-compatible and build records remain shared.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_slurm_dry_run_planning.py`, `tests/integration/pipeline/test_slurm_live_single_job.py`, `tests/integration/pipeline/test_slurm_live_afterok.py`.
- Required assertions or deferral reason: dry-run scripts include Apptainer exec wrappers with no build commands; live fake `sbatch` paths reuse existing manifests/status/cancel semantics.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_cli_slurm_dry_run.py`, `tests/e2e/test_cli_slurm_live_single_job.py`, `tests/e2e/test_cli_slurm_live_afterok.py`.
- Required assertions or deferral reason: CLI-selected SLURM plus Apptainer configs generate/submit wrapped scripts without real runtime requirements.

### Opt-In Suites

- Status: deferred.
- Markers affected: real SLURM/Apptainer/Singularity smoke.
- Required assertions or deferral reason: real runtime smoke remains optional Phase 5 work.

## Risks

- Build failures accidentally occur after script rendering or after partial live submission.
- SLURM manifests lose compatibility with status/cancel readers.
- Container command wrapping leaks configured environment values into metadata.
- Resource metadata implies Apptainer enforces CPU or memory instead of SLURM.
- Stage-specific container options are accidentally ignored in afterok mode.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm tests/unit/loom/cli/test_run.py
uv run pytest tests/contracts/test_slurm_manifest_contract.py tests/contracts/test_container_executor_contract.py
uv run pytest tests/integration/pipeline/test_slurm_dry_run_planning.py tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py
uv run pytest tests/e2e/test_cli_slurm_dry_run.py tests/e2e/test_cli_slurm_live_single_job.py tests/e2e/test_cli_slurm_live_afterok.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes

- Safe implementation slices: command metadata/wrapper first, target resolution second, CLI integration third, live/e2e coverage last.
- Tests to run with each slice: SLURM unit tests after wrapper work, CLI unit tests after target resolution, integration/e2e tests after planner integration.
- Decisions not to revisit: no new executor names, no build commands in scripts, no path translation, no MPI/site module policy, and no real runtime default tests.
- Stop conditions: composition requires a new scheduler backend, build resolution cannot be completed before rendering/submission, status/cancel manifests regress, or executable scripts require non-persisted secret materialization.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted suite and full PR gate passed
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager in this file before code changes.
- Final phase execution plan: refined in this planning pass; ready for implementation.
- Implementation summary: added `SlurmCommandArgv` metadata, a
  SLURM-owned Apptainer composition helper, container target-to-SIF resolution,
  path-parity bind injection for SLURM dry-run/live planning, run-level and
  stage-level container/Apptainer option threading, CLI build resolution before
  rendering or live `sbatch`, redacted command/build metadata, and focused
  unit/contract/integration/e2e coverage.
- Implementation validation:
  - Targeted SLURM and CLI unit suite passed:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/slurm tests/unit/loom/cli/test_run.py`:
    103 passed.
  - Targeted contract/integration/e2e suite passed:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_slurm_manifest_contract.py tests/contracts/test_container_executor_contract.py tests/integration/pipeline/test_slurm_dry_run_planning.py tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/e2e/test_cli_slurm_dry_run.py tests/e2e/test_cli_slurm_live_single_job.py tests/e2e/test_cli_slurm_live_afterok.py`:
    21 passed, 3 skipped.
  - Targeted Ruff and Pyright passed for touched implementation and test files.
  - `make validate-pr` passed outside the sandbox: Ruff passed; Pyright
    passed; default harness passed with 1868 passed, 26 skipped, 18 deselected;
    config-extra harness passed with 447 passed, 1906 deselected; `uv build`
    produced the source distribution and wheel. The same command was
    terminated in the sandbox after existing localhost authority-service tests
    hung under network restrictions.
  - `make test-summary` passed outside the sandbox and wrote
    `build/test-summary.md`; overall summary: 2344 passed, 18 skipped, 1922
    deselected.
- Refinement summary: not needed; implementation and validation passed without
  spending the phase refiner budget.
- PR preparation: PR #185 opened against `develop`; PR body drafted in
  `docs/roadmap/stage-18/phases/slurm-apptainer-composition-pr-body.md`
- Stack maintenance: root phase from `develop`
- Remaining blockers: none
