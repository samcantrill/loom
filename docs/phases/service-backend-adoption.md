# Phase 9 Execution Plan: System-Wide Service Backend Adoption

## Metadata

- Status: in_progress
- Feature focus: `Authority Runtime Unification`
- PR title:
  `Authority Runtime Unification - Phase 9: Service Backend Adoption`
- Branch: `codex/service-backend-adoption`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/service-backend-adoption`
- Phase execution plan path: `docs/phases/service-backend-adoption.md`
- Full plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Source phase: Phase 9 - System-Wide Service Backend Adoption
- Stack predecessor: none; Phase 8 merged before branch creation.
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after local validation,
  automated review, and GitHub checks pass.
- Workflow path: expanded path because this phase spans runtime construction,
  worker handoff records, SLURM paths, diagnostics, read models, docs, and
  examples.
- Successor dependency notes: Phase 10 must branch from Phase 9 after it
  merges because SQLite removal depends on service-backed parity.
- Plan quality gate: passed on 2026-05-10 in the implementation plan with no
  blocking or non-blocking findings.
- Plan quality gate loop budget: consumed by the recorded formal review; not
  reopened because plan content is unchanged.
- Draft pass: complete on 2026-05-10 by local managing-agent planning.
- Refine pass: complete on 2026-05-10 in the same artifact after source and
  harness inspection.
- Setup limitations: real external service, real multi-host, and real HPC
  tests remain out of default validation.
- Blockers: none.

## Objective

Adopt the Phase 7 service-backed authority configuration and Phase 8 deployment
profile machinery across runtime, worker/submitted handoff, SLURM, diagnostics,
and behavior-read entrypoints without switching defaults or removing
transitional SQLite authority.

## Full-Plan Context

Phases 1-8 established authority contracts, artifact boundaries, local runtime
guardrails, authority read models, a concrete service backend, and explicit HPC
deployment/fallback semantics. This phase makes those pieces operational across
supported call sites. Phase 10 remains responsible for changing the default
runtime selection and removing run-local SQLite authority.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; PR #116 is merged.
- Why this base branch is correct: Phase 8 metadata is recorded on `develop`,
  and no unmerged predecessor branch remains.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: delete the phase branch after merge if no
  successor branch is based on it.

## Source Phase Summary

- Goal: refactor Loom runtime and read systems to use, configure, diagnose,
  and support the concrete service/database backend.
- Required scope: public factory/configuration selection, CLI and Python
  construction, worker and submitted-job handoff, SLURM planning/submission
  status/cancel paths, diagnostics/preflight/status/catalog/plan reads, docs,
  examples, and tests.
- Required checkpoints: shared authority reference propagation, endpoint
  redaction, capability admission before irreversible work, live/deferred HPC
  profile separation, and no local lifecycle fallback for service-backed
  paths.
- Acceptance criteria: service-backed runtime and read paths work through
  public configuration, handoff records reconnect safely, deferred profiles
  refuse live commits, capability admission is consistent, tests/examples cover
  service-backed behavior, and SQLite remains transitional.

## Current Source And Harness Findings

- `create_run_store(AuthorityConfig(...))` already constructs service clients
  for co-located, managed-service, and allocation-scoped backends.
- `create_authority_backed_serial_run_store(...)` still defaults to direct
  SQLite authority and needs an authority-config path for service-backed local
  runtime adoption.
- Worker requests already carry `authority_attempt` lease and fencing metadata;
  they do not yet carry the shared authority reference/deployment profile.
- CLI stage, stage-job, prepared-run, and SLURM paths still construct local
  stores directly in several helpers.
- Phase 8 deployment preflight and deferred envelope helpers exist but are not
  yet wired into all runtime/submitted call sites.
- Import-boundary tests require keeping service/multiprocessing imports out of
  package roots.

## In-Scope Work

- Add service-aware authority configuration resolution for Python, CLI,
  subprocess worker, stage-job, and SLURM handoff paths.
- Extend authority-backed serial store construction to accept an
  `AuthorityConfig` while preserving transitional SQLite as an explicit bridge.
- Propagate `AuthorityReference` and deployment profile metadata into worker
  requests and submitted-operation metadata with redacted diagnostics.
- Gate serial, bounded parallel, subprocess worker, SLURM live worker,
  deferred worker, cancellation/status observation, and read-only inspection
  through the existing capability admission vocabulary.
- Wire service-backed store construction through CLI helpers and representative
  SLURM planning/status/cancel paths without exposing backend classes.
- Update docs/examples to select service-backed authority through public
  config/factory APIs.
- Add focused package, unit, integration, and e2e coverage for service-backed
  runtime and read paths.

## Out-of-Scope Work

- Changing the default runtime authority away from transitional SQLite.
- Removing `SQLitePerRunAuthorityStore` or its conformance coverage.
- Adding hosted production service operations, auth, tenancy, or real network
  topology probes.
- Treating deferred finalization as live worker authority.
- Broad refactors of the catalog projection or local materialization layout.

## Assumptions

- The deterministic local service fixture is the concrete backend for default
  tests.
- Handoff records may store safe authority references and redacted metadata,
  but not raw secret material in public diagnostics.
- CLI authority options should remain minimal and map directly onto
  `AuthorityConfig`; richer service operation commands can follow later.
- Transitional SQLite can remain the implicit default only until Phase 10.

## Scope Contract

Public callers select service-backed authority through `AuthorityConfig` and
public factory helpers. Worker/submitted handoff records must carry only
plain-data authority references plus deployment profile facts. Live worker
paths require live-authority capabilities and fencing material; deferred
finalization paths must omit live commit authority. Read-only diagnostics may
inspect local materialization, but service-backed behavior reads must come from
authority snapshots and submitted-operation records.

## Design Impact

- Maintainability: consolidates backend selection and admission checks instead
  of letting each CLI/runtime path invent service behavior.
- Extensibility: later backend kinds can use the same config/reference and
  handoff shapes.
- Domain neutrality: authority concepts stay generic to pipeline lifecycle and
  materialization, not any scientific domain.
- Source-tree boundaries: store contracts/config stay under
  `loom.pipeline.stores`; orchestration remains in
  `loom.pipeline.execution`; CLI modules remain presentation over public APIs.

## Future Compatibility

Phase 10 can remove transitional SQLite after this phase proves that runtime,
worker, submitted, and read entrypoints can operate through service-backed
authority. Future durable service implementations can replace the local
fixture behind the same factory path.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Switch the default in this phase | Phase 10 owns default selection and SQLite removal after adoption parity is proven. |
| Add backend-specific CLI/runtime branches | This would duplicate admission and redaction logic instead of using `AuthorityConfig`. |
| Let offline workers fall back to local status writes | Deferred finalization is evidence only; lifecycle truth must remain authority-backed. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Transitional SQLite remains the implicit default | Phase 9 must prove service-backed parity without combining removal risk | Phase 10 starts |
| CLI authority surface stays compact | This phase needs adoption, not a full service-operations CLI | Users need managed service lifecycle commands |

## Reviewability

- Expected PR size and shape: medium-to-large adoption PR with focused helpers,
  call-site wiring, docs/examples, and tests.
- Files and areas to inspect: store config/factory, execution adapter and
  worker models, CLI construction helpers, SLURM handoff/status/cancel paths,
  diagnostics/preflight, package import tests, docs/examples.
- Scope-control checks: no default switch, no SQLite removal, no hosted ops,
  no new heavyweight dependency, no local lifecycle fallback for service-backed
  paths.

## Implementation Steps

1. Add shared authority resolution/reference helpers and extend
   authority-backed serial store construction to accept service-backed configs.
2. Propagate authority references and deployment profiles into worker request
   and submitted-operation metadata; validate live versus deferred mode.
3. Wire CLI, continuation, and SLURM helpers through shared authority
   construction and admission checks.
4. Update diagnostics/preflight/status/catalog/plan examples so service-backed
   runs are read through authority snapshots and safe redacted references.
5. Add service-backed package/unit/integration/e2e tests and update docs.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_execution_api.py`.
- Required assertions: service selection and helper imports remain public
  where intended and do not import concrete service/multiprocessing modules
  through package roots.

### Unit Suite

- Status: required.
- Expected paths: store config/admission tests, execution model/adapter tests,
  CLI helper tests, SLURM submission/cancellation/status tests, diagnostics
  tests.
- Required assertions: environment/CLI/config resolution, reference redaction,
  worker handoff propagation, live/deferred refusal, and admission diagnostics.

### Contract Suite

- Status: required.
- Expected paths: existing authority store and run-store conformance tests.
- Required assertions: service backend remains in the conformance matrix while
  SQLite remains transitional.

### Integration Suite

- Status: required.
- Expected paths: service authority backend, local execution, subprocess/stage
  worker, SLURM fake flows, status/catalog/diagnostics/preflight over
  service-backed runs.
- Required assertions: representative mutating and read entrypoints work
  against the concrete backend.

### E2E Suite

- Status: required where deterministic.
- Expected paths: CLI run/status/stage or submitted-flow coverage using the
  deterministic local service fixture.
- Required assertions: user-facing command paths can select service-backed
  authority without exposing backend classes.

### Opt-In Suites

- Status: deferred.
- Markers affected: real HPC and real external service/multi-host markers.
- Required assertions or deferral reason: default validation must remain local
  and deterministic; real topology coverage remains opt-in.

## Risks

- Service process lifecycle in tests can leak if fixtures are not scoped
  carefully.
- Broad call-site wiring may accidentally switch defaults; tests must assert
  transitional SQLite remains explicitly available.
- Handoff records can expose endpoint/auth metadata if redaction is not applied
  consistently.
- SLURM live and deferred paths have different correctness semantics and must
  stay visibly separate.

## Validation Commands

Targeted development commands:

```sh
uv run --extra config pytest tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/executors/slurm/test_slurm_submission.py -q
uv run --extra config pytest tests/integration/pipeline/test_service_authority_backend.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_local_execution.py -q
uv run --extra config pyright
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: shared config/reference helpers first, worker
  handoff next, then CLI/SLURM/read-path adoption, then docs/tests.
- Tests to run with each slice: unit tests for touched helpers, then service
  integration tests, then final PR gates.
- Decisions the executor must not revisit: do not change defaults, do not
  remove SQLite, do not add hosted ops, do not treat deferred workers as live
  committers.
- Conditions that require stopping for the manager: service adoption requires
  a new heavyweight dependency, public API naming conflict, or hidden default
  switch.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-10.
- Final phase execution plan: completed on 2026-05-10.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: pending.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none.
