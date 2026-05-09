# Phase 7 Execution Plan: SLURM Acceptance, Docs, And Hardening

## Metadata

- Status: final phase execution plan
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 7: Acceptance, Docs, And Hardening`
- Branch: `codex/slurm-acceptance-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-acceptance-hardening`
- Phase execution plan path: `docs/phases/slurm-acceptance-hardening.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 7 - Preflight, Opt-In Cluster Acceptance, Docs, And Hardening
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after validation, automated review, PR CI, and target verification
- Workflow path: expanded path, because this phase consolidates public docs, preflight behavior, and opt-in real-cluster acceptance coverage
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v7.md`
- Plan quality gate loop budget: already used and passed before Phase 1
- Draft pass: complete on 2026-05-08
- Refine pass: not needed; scope is bounded to final v7 hardening
- Setup limitations: default validation remains cluster-free; real SLURM coverage is skipped unless explicitly enabled
- Blockers: none

## Objective

Finish the v7 live SLURM user surface by tightening preflight diagnostics, adding skipped-by-default real-cluster acceptance tests, documenting live submit/status/cancel workflows, and proving artifact safety around scheduler metadata.

## Full-Plan Context

Phases 1 through 6 are merged. The codebase now has shared submitted lifecycle records, live manifest models, live single-job and afterok submission, scheduler-aware status, and submitted-job cancellation. Phase 7 must not add new scheduler modes, retries, cleanup, remote stores, containers, or default real-cluster dependencies.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none; Phases 1 through 6 are merged
- Why this base branch is correct: all earlier v7 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after squash merge if no successor is stacked on this branch

## Source Phase Summary

- Goal: complete operational validation, documentation, and final edge-case coverage for v7 live SLURM operations.
- Required scope: preflight check IDs, opt-in real-cluster acceptance scaffold, docs/examples, fake-command regression coverage, and secret-safety checks.
- Required checkpoints: no accidental real SLURM test execution, no default CI dependency on SLURM, no new core scheduler behavior beyond hardening, and no secret-bearing artifact expansion.

## Current Source And Harness Findings

- Preflight already has stable checks for SLURM mode, launcher argv, `sbatch`, resource mapping, local run URI, and generated path resolution.
- Missing Phase 7 preflight coverage: optional `squeue`/`sacct`, `scancel` availability, active submitted work, and writable generated script/log paths.
- Existing docs still describe v6 dry-run as the implemented state and mention live operations as deferred.
- Default tests use fake command runners and are cluster-free; no real SLURM acceptance scaffold exists.
- The repo already has a `slurm` pytest marker, and default harnesses exclude it.
- Control checkout has unrelated local changes outside this phase; Phase 7 work stays in this worktree and must not depend on them.

## In-Scope Work

- Extend stable preflight IDs and checks for optional SLURM status/cancel commands and generated-path writability.
- Add a run preflight check for active submitted SLURM operations when inspecting or resuming an existing run.
- Preserve `sbatch` as a live-submission failure and as a dry-run warning.
- Keep missing `squeue`/`sacct`/`scancel` as warnings in preflight because `loom status --jobs` and `loom cancel --jobs` perform their own operation-time checks.
- Add unit and contract coverage for the new preflight IDs and JSON shape.
- Add integration/e2e fake-command coverage that exercises submit, status, and cancel together without real SLURM.
- Add an opt-in real SLURM acceptance suite marked `slurm` and `slow`, gated by explicit environment variables, with helper timeouts and cleanup guidance.
- Update SLURM, preflight, CLI, testing, and example documentation for live submission, status, cancellation, uncertainty, partial submission, active-job guards, and acceptance-suite usage.
- Add a small SLURM live example directory without changing unrelated existing example edits in the control checkout.
- Add or tighten secret-safety regression tests for generated scripts/manifests/status/cancellation metadata.

## Out-of-Scope Work

- No default real-cluster CI requirement.
- No cleanup command, retry policy, exact submission selector, job arrays, controller mode, remote store support, or container wrapping.
- No certification matrix for all SLURM site configurations.
- No Python SLURM dependency.

## Assumptions

- Preflight can probe command availability with `shutil.which` but must not submit jobs.
- Writable generated-path checks may create and remove a small temporary probe under the selected local run path or nearest existing parent.
- Real acceptance tests can require a shared filesystem root and may skip optional cases when a site does not expose accounting quickly enough.
- Documentation examples can be runnable templates rather than executed by default docs tests.

## Scope Contract

Phase 7 must make v7 live SLURM operationally reviewable without widening the scheduler feature set. Default validation remains local and deterministic; real cluster checks require explicit opt-in. User-facing docs must describe what is implemented now, what remains deferred, and how to inspect or cancel partial submissions safely.

## Design Impact

- Maintainability: final preflight IDs and docs align the public surface with the implemented live operations.
- Extensibility: the acceptance scaffold gives future SLURM work a controlled place for real-cluster coverage.
- Domain neutrality: real tests and examples use generic tiny pipelines, not project-specific science code.
- Source-tree boundaries: scheduler-specific probes remain in diagnostics and SLURM executor-adjacent code without new runtime dependencies.

## Future Compatibility

The opt-in suite and documented acceptance environment variables can grow in v8 without changing default CI. The preflight IDs leave space for future exact cancellation or cleanup checks.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Run real SLURM tests in default validation | Default validation must stay deterministic and cluster-free. |
| Add a cleanup command in final hardening | Cleanup semantics are explicitly deferred and need their own policy. |
| Keep docs v6-oriented until later | Users need accurate live submit/status/cancel guidance once v7 merges. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Real acceptance suite is an opt-in scaffold, not a site certification matrix | SLURM sites vary too much for one default matrix. | Maintainers identify specific site profiles that need codified acceptance cases. |
| Preflight warns on optional status/cancel commands instead of modeling operation intent | `loom status --jobs` and `loom cancel --jobs` already enforce operation-time requirements. | A future preflight mode accepts an explicit operation intent such as status or cancel. |

## Reviewability

- Expected PR size and shape: diagnostics/preflight hardening, opt-in tests, docs, examples, and matrix-focused regression tests.
- Files and areas to inspect: stable preflight IDs, generated-path writability probe side effects, opt-in test gating, docs accuracy, and secret-safety assertions.
- Scope-control checks: no default real scheduler dependency, no cleanup/retry implementation, no future scheduler modes.

## Implementation Steps

1. Add and test final SLURM preflight checks.
2. Add fake-command submit/status/cancel flow and secret-safety regressions.
3. Add opt-in real SLURM acceptance scaffold with explicit environment gating.
4. Update feature docs and add the live SLURM example directory.
5. Run targeted tests, `make validate-pr`, and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/`
- Required assertions or deferral reason: new acceptance helpers and docs additions do not introduce import-time SLURM or optional config dependencies.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`, `tests/unit/loom/pipeline/executors/slurm/`
- Required assertions or deferral reason: preflight command availability, active submitted work, writable generated paths, and secret-safety branches.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_preflight_contract.py`, `tests/contracts/test_slurm_manifest_contract.py`
- Required assertions or deferral reason: stable preflight JSON IDs and manifest safety schema remain explicit.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/`, `tests/integration/pipeline/`
- Required assertions or deferral reason: fake-command submit/status/cancel flow and preflight behavior remain cluster-free.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/`
- Required assertions or deferral reason: public CLI fake-runner flow for live submit, status, and cancellation.

### Opt-In Suites

- Status: required but skipped by default
- Markers affected: `slurm`, `slow`
- Required assertions or deferral reason: real single-job, afterok, status, cancellation, logs, and manifest records are covered behind explicit environment variables.

## Risks

- Preflight writability probes must not leave files or create full run state.
- Active submitted-work checks must not require the run directory for new runs.
- Docs must not imply automatic cleanup, retries, or exact submission selection.
- Real acceptance tests must fail loudly only after users explicitly opt in.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/contracts/test_cli_preflight_contract.py tests/integration/diagnostics tests/integration/pipeline tests/e2e -m "not slurm and not optional_dependency"
uv run pytest tests/slurm_acceptance -m slurm
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes

- Keep all implementation in this branch/worktree.
- Preserve unrelated dirty control-checkout files.
- If real SLURM is unavailable locally, do not force it; prove the opt-in suite skips by default and document how maintainers enable it.
- Stop only for blockers that require changing previously accepted Phase 1-6 contracts.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed
- PR review: used by manager local review on 2026-05-08; no blocking findings
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete
- Final phase execution plan: complete
- Implementation summary: complete. Added stable preflight IDs and checks for
  optional SLURM status/cancel commands, active submitted work, and writable
  generated paths; added fake-command submit/status/cancel e2e coverage with a
  secret-safety assertion; added skipped-by-default real SLURM acceptance tests
  for single-job success, afterok dependencies, and cancellation; updated SLURM,
  preflight, CLI, testing, and example docs; added
  `examples/execution/slurm/live/`.
- Implementation validation: complete. `make validate-pr` passed on
  2026-05-08 after Ruff, Pyright, default suite, config-extra suite, and build.
  `make test-summary` passed on 2026-05-08 with package 52 passed / 1 skipped,
  unit 734 passed / 1 skipped, contract 73 passed / 2 skipped, integration 45
  passed / 7 skipped / 10 deselected, e2e 36 passed / 1 deselected, and
  config-extra 413 passed / 943 deselected. `uv run pytest tests/slurm_acceptance
  -m slurm` collected three tests and skipped all because
  `LOOM_RUN_SLURM_ACCEPTANCE=1` and `LOOM_SLURM_ACCEPTANCE_ROOT` were not set.
- Refinement summary: not needed; targeted validation and final PR validation
  passed after updating the stable-ID contract snapshot.
- Blocker-resolution summary: 0/3 used
- PR preparation: complete. PR #94 opened at
  https://github.com/samcantrill/loom/pull/94 against `develop` from
  `codex/slurm-acceptance-hardening`; target/head verification passed; GitHub
  checks passed before the final phase-artifact metadata update.
- Stack maintenance: no successor branch exists; this is the final v7 phase
- Remaining blockers: none known
