# Phase 5 Execution Plan: Preflight, Docs, And Opt-In Runtime Smoke

## Metadata

- Status: in_progress
- Feature focus: HPC Container Execution
- PR title: `HPC Container Execution - Phase 5: Preflight Docs And Smoke Hooks`
- Branch: `codex/container-preflight-docs`
- Worktree: `/home/samcantrill/work/loom-worktrees/container-preflight-docs`
- Phase execution plan path: `docs/roadmap/stage-18/phases/container-preflight-docs.md`
- Full plan: `docs/roadmap/stage-18/implementation-plan.md`
- Source phase: Stage 18 Phase 5, `container-preflight-docs`
- Stack predecessor: none
- Base branch: `origin/develop` at `bbf6ac1`
- Target branch: `develop`
- PR: pending
- Merge eligibility: pending validation and automated review
- Workflow path: expanded path
- Successor dependency notes: final Stage 18 phase; no product successor branch depends on this branch.
- Plan quality gate: passed in the implementation plan on 2026-05-17
- Draft pass: completed by manager before implementation
- Refine pass: completed in this planning pass because this phase validates cross-cutting diagnostics and docs
- Blockers: none

## Objective

Finish Stage 18 by adding cheap selected-executor preflight coverage for container build targets, direct Apptainer/Singularity execution, and SLURM plus Apptainer composition, then update feature docs and add explicit opt-in smoke hooks for real runtimes without making Docker, Apptainer, Singularity, SLURM, registries, fakeroot, or network required by default.

## In-Scope Work

- Extend stable preflight IDs for selected container build, Apptainer/Singularity, SLURM/container compatibility, and related filesystem/resource checks.
- Parse existing `adapter_options.container`, `adapter_options.container_build`, `adapter_options.apptainer`, `adapter_options.singularity`, and `adapter_options.slurm` payloads through the same records used by Phases 1-4.
- Report daemon-free and cluster-free diagnostics for command presence, image/SIF reference shape, build target validity, local source/output presence, bind roots, path parity, writable run paths, required host environment variable names, GPU flags, resource ownership, and SLURM/container compatibility.
- Keep diagnostic details JSON-safe and redacted: environment values, build args, command secrets, and raw service metadata must not be persisted.
- Update container, SLURM, preflight, provenance, and testing feature docs to match implemented schema names and default validation behavior.
- Add opt-in smoke tests or hooks for real Docker, Apptainer/Singularity command availability, Apptainer SIF build, and SLURM acceptance paths that skip unless explicitly enabled.

## Out-of-Scope Work

- Any default test or preflight behavior that pulls images, contacts registries, probes network services, submits real SLURM jobs, runs real container commands, or requires fakeroot.
- Registry/auth helpers, image publishing, external/site build services, cleanup/retention policy, path translation, MPI/rank policy, or site module setup.
- Changing the public `container_build` merge semantics, build output authority model, or SLURM executor names.
- Retrofitting Docker direct execution to consume build targets during this phase.

## Assumptions

- Direct Apptainer/Singularity preflight can mirror the existing Docker preflight shape while preserving Apptainer-specific clean environment and GPU flag language.
- SLURM plus Apptainer preflight should run only when a selected SLURM runtime uses the `container` namespace.
- `container_build` checks can validate authored targets and local paths without invoking builders; policy checks remain advisory because actual builds happen at run time.
- Existing preflight groups are sufficient; no new top-level preflight group is needed.

## Design Impact

- Maintainability: diagnostics stay in `loom.diagnostics.preflight` and consume executor-owned record parsers rather than duplicating command semantics.
- Extensibility: stable check IDs give Stage 19 reliability policy and future event projection durable facts without parsing logs or generated scripts.
- Domain neutrality: examples use generic stage and container names only; no package manager, dataset, model, module, or site policy is encoded.
- Source-tree boundaries: shared container/build records remain import-light, Apptainer command options stay adapter-owned, and SLURM remains scheduler authority.

## Future Compatibility

- Stage 19 can classify readiness failures across build target, runtime command, scheduler command, resource mapping, and filesystem categories.
- Stage 20 can project preflight facts into event streams using stable IDs and JSON-safe details.
- Stage 21 can reason about local build outputs and generated artifacts as cleanup candidates without treating them as authoritative run state.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Run `apptainer --version`, `docker version`, or `sbatch` probes in default preflight | Default validation must stay cheap and environment-independent. PATH checks are enough for readiness diagnostics. |
| Add a new `containers` preflight group | Existing runtime/executor/resources/filesystem groups already express the ownership boundaries. |
| Deep-merge build targets for preflight convenience | Stage 18 explicitly keeps whole-namespace replacement semantics. |
| Add site-specific smoke fixtures | The repository must stay domain-neutral and not assume module systems, images, registries, or cluster partitions. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Build target output checks are local path/reference checks only | Default preflight must not inspect registries or run real builders | A future explicit expensive preflight mode is approved. |
| Direct Apptainer CPU/memory checks are advisory summaries | The direct executor does not allocate scheduler resources | A future runtime policy owns cgroups, scheduler integration, or resource enforcement. |
| Smoke tests are environment-gated acceptance hooks | Real runtimes and clusters are site-specific | Release policy requires live evidence in a maintained environment. |

## Reviewability

- Expected PR size and shape: medium diagnostics/docs PR touching preflight models, preflight runner helpers, focused diagnostics tests, feature docs, and optional acceptance hooks.
- Files and areas to inspect: stable ID additions, selected-runtime detection, redaction, filesystem side effects, docs/schema alignment, and smoke-test skip gates.
- Scope-control checks: no real runtime invocation in default preflight, no network/registry probes, no hidden build behavior, no new scheduler executor, and no domain-specific examples.

## Implementation Steps

1. Extend stable check IDs and add selected container build plus Apptainer/Singularity target collection helpers.
2. Implement runtime/executor/resource/filesystem checks for build targets, direct Apptainer/Singularity, and SLURM/container compatibility with redacted plain-data details.
3. Add focused unit/contract/CLI tests for stable IDs, selected namespace behavior, JSON-safe details, missing commands, missing SIF/output paths, required env variables, and SLURM/container compatibility.
4. Update feature docs and add explicit opt-in real-runtime smoke hooks that skip unless the user sets enabling environment variables.
5. Run targeted diagnostics/package/e2e checks, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package`.
- Required assertions or deferral reason: optional runtime imports remain cheap and do not require Docker, Apptainer, Singularity, SLURM, images, registries, fakeroot, or network.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/diagnostics`, focused optional smoke tests if added.
- Required assertions or deferral reason: stable selected checks for container builds, Apptainer/Singularity command/options/image/environment, filesystem/path parity, resource mapping, and redaction.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_diagnostics_preflight_contract.py`, `tests/contracts/test_cli_preflight_contract.py`.
- Required assertions or deferral reason: stable check IDs and JSON envelope remain deterministic.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/diagnostics`.
- Required assertions or deferral reason: preflight CLI/integration coverage keeps selected groups and JSON output working with config-backed runtime options.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_cli_slurm_dry_run.py`, plus existing fake container/SLURM paths where applicable.
- Required assertions or deferral reason: docs/script-facing SLURM dry-run behavior remains compatible with container wrapping and no real runtime requirement.

### Opt-In Suites

- Status: required as skipped-by-default hooks.
- Markers affected: `slow`, `optional_dependency`, existing `slurm`, and new Docker/Apptainer runtime smoke markers if needed.
- Required assertions or deferral reason: real Docker, Apptainer/Singularity command, SIF build, and SLURM acceptance checks are present but skipped unless explicitly enabled by environment variables.

## Risks

- Stable check ID churn breaks external preflight consumers.
- Diagnostics accidentally leak environment values, build args, or command secrets.
- Preflight creates run state instead of temporary probe files.
- Docs promise behavior that was deferred from Stage 18.
- Optional smoke gates accidentally run in default validation.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/diagnostics tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py tests/integration/diagnostics tests/e2e/test_cli_slurm_dry_run.py tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes

- Safe implementation slices: stable IDs and helpers first, selected checks second, tests third, docs/smoke hooks last.
- Tests to run with each slice: diagnostics unit/contract tests after code changes; integration/CLI tests after JSON/formatting assertions; package tests after acceptance hooks.
- Decisions not to revisit: no default runtime invocation, no registry/network probes, no target deep merge, no site policy, no path translation, no MPI/rank policy.
- Stop conditions: preflight cannot remain cheap by default, docs require unimplemented behavior, or stable IDs conflict with existing diagnostics conventions.

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
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: root phase from `develop`
- Remaining blockers: none
