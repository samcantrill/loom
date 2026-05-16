# Phase 5 Execution Plan: Docker Examples Acceptance

## Metadata

- Status: pr_open
- Feature focus: Docker Container Executor
- PR title: `Docker Container Executor - Phase 5: Examples And Acceptance`
- Branch: `codex/docker-examples-acceptance`
- Worktree: `/home/samcantrill/work/loom-worktrees/docker-examples-acceptance`
- Phase execution plan path: `docs/roadmap/stage-17/phases/docker-examples-acceptance.md`
- Full plan: `docs/roadmap/stage-17/implementation-plan.md`
- Source phase: Stage 17 Phase 5, `docker-examples-acceptance`
- Stack predecessor: none; Phase 4 is merged
- Base branch: `develop`
- Target branch: `develop`
- PR: [#175](https://github.com/samcantrill/loom/pull/175)
- Merge eligibility: pending GitHub CI, manager automated review, and final
  target-branch verification
- Workflow path: fast path
- Successor dependency notes: this is the final Stage 17 phase; no successor
  phase branch depends on this branch.
- Plan quality gate: passed in the implementation plan on 2026-05-16 with no blockers
- Plan quality gate loop budget: consumed by the existing passed gate; no
  further plan review is needed for this phase.
- Draft pass: completed in this planning pass
- Refine pass: not needed on the fast path unless docs/example validation
  exposes unresolved public behavior
- Setup limitations: default validation must stay Docker-daemon-free,
  network-free, registry-free, and SDK-free
- Blockers: none

## Objective

Publish Stage 17 Docker executor examples, feature documentation, and
acceptance tests that demonstrate normal pipeline execution, prepared-stage
command shape, preflight diagnostics, failure inspection, and runtime/profile
configuration without making Docker a default validation dependency.

## Full-Plan Context

Phases 1 through 4 established the shared container records, Docker command
runner, `DockerExecutor`, CLI selection, and cheap selected-Docker preflight
checks. This phase consumes those surfaces in user-facing docs and examples.
Because this is the final phase, the PR must also carry final suite-level
evidence and avoid deferring any remaining Stage 17 example obligation.

Future roadmap work that must stay out of this PR includes image builds,
registry authentication, automatic pulls, Docker Compose, Kubernetes,
Apptainer/Singularity, SLURM-container composition, advanced GPU mapping,
whole-controller-in-container mode, security-sandbox claims, and mandatory live
Docker validation.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 4 merged to `develop`.
- Why this base branch is correct: Phase 5 depends on the merged Docker
  executor and preflight diagnostics from Phases 1 through 4.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: no successor phase should depend on
  `codex/docker-examples-acceptance`; delete the branch after merge when
  GitHub and local refs are clean.

## Source Phase Summary

- Goal: provide the requested Docker stage and pipeline examples, then harden
  final validation evidence for review.
- Required scope: feature/user docs, example configs and fixtures,
  docs/example tests, fake-runner default validation, and optional live Docker
  smoke guidance outside the default harness.
- Required checkpoints: examples use `container` plus `docker` adapter
  namespaces, show `loom run --executor docker`, show prepared-stage Docker
  command shape, show preflight pass/fail checks, show inspectable failure
  surfaces, avoid raw secret persistence, and avoid Docker as a security
  sandbox claim.
- Acceptance criteria: default tests exercise product config/executor paths
  without real Docker, and final PR evidence includes `make validate-pr` and
  `make test-summary`.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `examples/README.md` and `examples/execution/README.md` own user-facing
    example catalog routing.
  - `tests/integration/docs/test_v0_python_examples.py` validates example
    manifests and runs all smoke Python entrypoints.
  - `docs/features/container-executors.md`, `docs/features/preflight.md`,
    `docs/features/execution.md`, `docs/features/runtime-resources.md`,
    `docs/features/provenance.md`, `docs/features/reliability.md`, and
    `docs/features/testing.md` are the cross-feature docs named by the
    implementation plan.
  - `DockerExecutor` launches the built `docker run` argv through
    `SubprocessDockerCommandRunner` by default, making a fake `docker` command
    on `PATH` sufficient for daemon-free CLI examples.
- Existing tests or harness behavior:
  - Smoke example scripts run from the repo root with
    `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` set to temp
    directories.
  - CLI examples must have `## Workflow` and `## Variants` README sections.
  - Relevant CLI examples should include explicit co-located authority
    variants.
- Import-boundary or dependency constraints:
  - Examples and docs tests must not add Docker SDK, network, registry, or real
    daemon requirements.
  - Runtime fake Docker helpers may live under `examples/`; runtime package
    code must not import example helpers.

## In-Scope Work

- Add a Docker execution example under
  `examples/execution/containers/docker/` with runnable smoke entrypoints for:
  - normal `loom run --executor docker` pipeline execution through a fake
    `docker` command on `PATH`;
  - selected-Docker preflight pass/fail inspection;
  - Docker worker failure inspection through existing status/log surfaces.
- Add example configs and stages that are domain-neutral and use
  `adapter_options.container` plus `adapter_options.docker`.
- Add README guidance for the prepared-stage Docker command shape and an
  optional live Docker smoke path gated by explicit user setup.
- Add or update feature docs to describe the implemented Stage 17 Docker
  behavior, stable preflight IDs, path-parity and redaction boundaries,
  failure inspection, provenance facts, and optional validation strategy.
- Add docs/example tests for the v17 Docker example catalog entry and coverage
  document.

## Out-of-Scope Work

- Runtime product behavior changes unless a docs/example test exposes a narrow
  Stage 17 regression.
- Image build commands, registry auth, pulls, Compose, Kubernetes,
  Apptainer/Singularity, SLURM-container composition, advanced GPU mapping, and
  controller-in-container examples.
- Requiring real Docker, daemon access, network access, registries, or Docker
  SDKs in `make validate-pr`.
- Treating Docker as a security sandbox for untrusted configs, images, or
  project code.

## Assumptions

- Daemon-free smoke examples using the real CLI and a fake `docker` command are
  sufficient default acceptance evidence for Stage 17.
- Optional live Docker validation can be documented as manual guidance because
  no default CI Docker daemon is required by the stage plan.
- The example pipeline may use the same synthetic numeric stages as other
  examples as long as the Docker executor path and container adapter options
  are exercised.

## Scope Contract

No new runtime public contract is introduced in this phase. The public behavior
documented and tested is the existing Stage 17 contract:

- `loom run CONFIG --executor docker` launches selected prepared stage attempts
  through `DockerExecutor`.
- Authored Docker configuration lives in runtime/profile adapter options under
  `container` and `docker`; semantic stage specs do not gain Docker fields.
- Stage 17 requires path-parity mounts for host-visible run and artifact paths.
- Docker preflight is cheap and reports stable selected-executor checks without
  pulling images or contacting registries.
- Failure inspection uses existing `loom status` and `loom logs` surfaces.
- Persisted Docker metadata and diagnostics are redaction-safe and must not
  include raw environment values.

## Design Impact

- Maintainability: docs and examples reuse the existing example harness and
  fake-command style rather than adding a Docker-specific test runner.
- Extensibility: the container example layout leaves room for Stage 18
  Apptainer/Singularity and SLURM-container examples under
  `examples/execution/containers/`.
- Domain neutrality: examples use generic numeric stages and local/CI workflow
  language only.
- Source-tree boundaries: runtime code remains unchanged unless needed for a
  narrow bug; example helpers stay under `examples/`.

## Future Compatibility

- Stage 18 can add `examples/execution/containers/apptainer/` or
  `examples/execution/containers/slurm-apptainer/` without changing the Docker
  example contract.
- Stage 19 can add retry/timeout docs that consume the Docker process facts
  documented here.
- Stage 20 can project the same executor/preflight facts into runtime events.
- Future image lock or live Docker validation work can strengthen the optional
  smoke guidance without changing default daemon-free acceptance.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Make the smoke example require a real Docker daemon | Violates the stage constraint that default validation must be Docker-free. |
| Document whole-controller-in-container execution | Explicitly out of scope for Stage 17 and conflicts with the approved per-stage executor interpretation. |
| Add a Docker SDK or testcontainer dependency | The stage requires Docker CLI only and no heavyweight runtime dependency. |
| Mark all Docker examples manual | Would fail the Stage 17 acceptance goal that examples exercise product paths in default validation. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Fake Docker command backs default example smoke tests | Keeps examples deterministic without daemon/network access | Maintainers require hosted live Docker evidence before release. |
| Live Docker instructions are manual | Site image contents, installed packages, and path mounts are environment-specific | A stable project image or image build stage is approved. |
| Prepared-stage Docker example is documented as command shape | Public CLI does not expose a one-shot Docker stage command separate from normal run orchestration | A future stage adds a direct prepared Docker command or public executor demo API. |

## Reviewability

- Expected PR size and shape: docs/example PR with a small example helper,
  smoke scripts, manifest/docs tests, and feature doc updates.
- Files and areas to inspect: example fake Docker command parsing, README
  commands, adapter option shapes, stable check IDs, redaction language, and
  optional live Docker gating.
- Scope-control checks: no runtime dependency additions, no Docker SDK, no
  registry or daemon requirement, no whole-controller examples, and no
  unrelated docs restructure.

## Implementation Steps

1. Add the Docker example directory with configs, stages, fake Docker helper,
   and smoke scripts.
2. Update example catalog READMEs and add container example coverage docs.
3. Update feature docs for implemented Stage 17 Docker behavior, preflight,
   provenance, reliability, and validation notes.
4. Add docs/example tests for the v17 Docker example and coverage links.
5. Run focused docs/example and Docker-related tests, then the final PR gates.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package`.
- Required assertions or deferral reason: imports remain cheap and Docker SDKs
  are not required.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors`,
  `tests/unit/loom/diagnostics`, and docs/example-adjacent unit coverage.
- Required assertions or deferral reason: Docker command, executor, container,
  and diagnostics unit coverage remains green after docs/example additions.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts`.
- Required assertions or deferral reason: stable Docker command, container, and
  preflight contracts remain green.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/docs`,
  `tests/integration/diagnostics`, and `tests/integration/pipeline`.
- Required assertions or deferral reason: smoke example scripts execute, Docker
  preflight examples remain redaction-safe, and fake-runner Docker pipeline
  product paths remain green.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e`.
- Required assertions or deferral reason: broad CLI regressions pass; no new
  e2e Docker daemon requirement is introduced.

### Opt-In Suites

- Status: deferred.
- Markers affected: none planned unless a live Docker smoke test is added.
- Required assertions or deferral reason: optional live Docker acceptance is
  documented as manual guidance outside default validation for Stage 17.

## Risks

- Examples could accidentally validate a fake-only path rather than the public
  `DockerExecutor` and CLI path.
- Docs could imply Docker isolates untrusted code or supports whole-controller
  container mode.
- Config snippets could use the wrong public shape, especially string image
  shorthand instead of the authored mapping shape.
- Smoke scripts could become too slow if each entrypoint starts unnecessary
  services.

## Validation Commands

Targeted development commands:

```sh
uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py
uv run --extra config pytest tests/integration/diagnostics tests/integration/pipeline/test_docker_executor_integration.py tests/unit/loom/pipeline/executors tests/unit/loom/diagnostics tests/contracts/test_docker_command_contract.py tests/contracts/test_container_executor_contract.py tests/contracts/test_diagnostics_preflight_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: example directory first, catalog/docs second,
  docs tests third, final validation last.
- Tests to run with each slice: run the new example scripts through
  `tests/integration/docs/test_v0_python_examples.py` after catalog changes;
  run Docker diagnostics/executor tests after feature docs and examples are in
  place.
- Decisions the executor must not revisit: Docker remains per-stage, config
  stays in `adapter_options.container` plus `adapter_options.docker`, live
  Docker is optional, and Docker is not a security sandbox claim.
- Conditions that require stopping for the manager: examples require product
  behavior not implemented by Phases 1 through 4, default validation requires a
  real Docker daemon, or the fake command requires runtime package changes
  beyond a narrow bug fix.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; not needed on fast path if targeted
  and final validation pass
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-16 in this phase branch.
- Final phase execution plan: complete for fast-path implementation.
- Implementation summary: added `examples/execution/containers/docker/` with
  daemon-free smoke scripts for `loom run --executor docker`, selected-Docker
  preflight pass/fail diagnostics, and Docker failure inspection through status
  and logs. Added a fake `docker` command helper that executes the prepared
  worker command locally while preserving the public Docker executor and CLI
  path. Updated feature docs, example catalogs, and container example coverage
  to document per-stage Docker execution, adapter option shape, path parity,
  stable preflight IDs, redaction, failure inspection, and optional live Docker
  guidance.
- Implementation validation:
  - `uv run --extra config python examples/execution/containers/docker/run_docker_pipeline.py`: passed; reported `run_status: SUCCEEDED`, `seed_executor: docker`, and `fake_docker_call_count: 2`.
  - `uv run --extra config python examples/execution/containers/docker/run_preflight.py`: passed; reported Docker command pass, artifact-root visibility pass, and missing-Docker command fail.
  - `uv run --extra config python examples/execution/containers/docker/run_failure_diagnostics.py`: passed; reported `run_status: FAILED`, `failure_executor: docker`, `failure_exit_code: 1`, and stderr availability.
  - `uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py`: passed, `33 passed`.
  - `uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/diagnostics tests/integration/pipeline/test_docker_executor_integration.py tests/unit/loom/pipeline/executors tests/unit/loom/diagnostics tests/contracts/test_docker_command_contract.py tests/contracts/test_container_executor_contract.py tests/contracts/test_diagnostics_preflight_contract.py`: passed, `261 passed`.
  - `uv run ruff check examples/execution/containers/docker tests/integration/docs/test_v0_python_examples.py`: passed.
  - `make validate-pr`: passed; Ruff, Pyright (`0 errors`), default harness (`1751 passed, 26 skipped, 18 deselected`), config-extra harness (`446 passed, 1788 deselected`), and build passed.
  - `make test-summary`: passed; package `100 passed, 1 skipped`, unit `1228 passed, 7 skipped, 1 deselected`, contract `251 passed, 2 skipped`, integration `157 passed, 8 skipped, 13 deselected`, e2e `43 passed, 2 deselected`, config-extra `446 passed, 1788 deselected`, overall `2225 passed, 18 skipped, 1804 deselected`.
- Refinement summary: no separate phase-refiner pass was needed; local fixes
  adjusted the preflight example's expected missing-command exit code and reset
  fake Docker logs between example invocations.
- Blocker-resolution summary: unused.
- PR preparation: PR body drafted in
  `docs/roadmap/stage-17/phases/docker-examples-acceptance-pr-body.md`; PR
  [#175](https://github.com/samcantrill/loom/pull/175) opened against
  verified `develop` from `codex/docker-examples-acceptance`.
- Stack maintenance: root phase from `develop`; no predecessor.
- Remaining blockers: none.
