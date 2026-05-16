# Phase 6 Execution Plan: Read-Only Inspection And Finalization

## Metadata

- Status: in_progress
- Feature focus: Reliability Policies And Transactions
- PR title: `Reliability Policies And Transactions - Phase 6: Read-Only Inspection And Finalization`
- PR: pending
- Branch: `codex/reliability-inspection-finalization`
- Worktree: `/home/samcantrill/work/loom-worktrees/reliability-inspection-finalization`
- Phase execution plan path: `docs/roadmap/stage-19/phases/reliability-inspection-finalization.md`
- Full plan: `docs/roadmap/stage-19/implementation-plan.md`
- Source phase: Phase 6, `reliability-inspection-finalization`
- Stack predecessor: none; Phases 1 through 5 are merged into `develop`
- Base branch: `develop` at `ece9aef` after Phase 5 merge metadata
- Target branch: `develop`
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-16 in the selected implementation plan
- Draft pass: completed by manager-local planning in this assignment
- Refine pass: completed by manager-local planning after reading diagnostics,
  CLI status/backend, runner runtime metadata, reliability models, and store
  read models
- Blockers: none

## Objective

Expose Stage 19 reliability facts through read-only inspection surfaces and
complete final documentation and validation evidence. Users should be able to
inspect selected reliability policy, status detail, transaction state, retry
decisions, timeout outcomes, and unsupported timeout evidence without parsing
executor logs, reading private store files, or invoking mutating commands.

## Current Source And Harness Findings

- `StageLifecycleSnapshot` and `AuthoritativeRunSnapshot` already carry
  reliability policy facts, status details, transactions, retry decisions, and
  timeout outcomes.
- `loom backend inspect --format json` already returns raw stage snapshots, but
  text output only reports generic stage counts and does not call out
  reliability facts.
- `loom status` uses `loom.diagnostics.inspection.inspect_run_status` and is
  the natural narrow CLI surface for stage-level status plus reliability
  summary facts.
- The runner writes runtime metadata with resolved reliability options, but the
  selected per-stage policy is not yet persisted as a `ReliabilityPolicyFact`
  during ordinary execution. Phase 6 should record those read-model facts
  before relying on inspection to expose selected policy.
- Preflight already reports unsupported timeout capability diagnostics. Runtime
  timeout execution records unsupported timeout outcomes where selected policy
  reaches an executor that cannot enforce or observe it.

## In-Scope Work

- Persist selected per-stage reliability policy facts from resolved runtime
  options during runner startup.
- Add read-only diagnostics summaries over authoritative reliability facts.
- Add compact reliability summaries to existing `loom status` JSON/text output.
- Add backend inspection counts for reliability facts and compact text
  presentation, while preserving raw JSON stage snapshot facts.
- Update feature docs for final Stage 19 behavior and Stage 20/21 deferrals.
- Add targeted package, unit, diagnostic, CLI, and integration coverage.

## Out-of-Scope Work

- New mutating retry, cleanup, retention, event, or notification commands.
- New provider, scheduler, service, telemetry, or plugin integrations.
- Event-sink grammar, callbacks, or Stage 20 event projections.
- Cleanup/deletion/retention enforcement or Stage 21 garbage collection.
- Executor-local retry loops or backend-specific policy keys.

## CLI Decision

CLI output is included, but only by enriching existing read-only commands:

- `loom status RUN_URI` gains compact reliability summaries in JSON and text
  for stages with reliability facts.
- `loom backend inspect RUN_URI` gains reliability counts in JSON/text and
  continues to expose raw authoritative reliability records in JSON stage
  snapshots.

No new `loom reliability`, `loom retry`, `loom cleanup`, or `loom inspect`
command is added. This keeps Phase 6 user-visible behavior narrow and avoids
implying that retry, cleanup, event sinks, or retention can be controlled from
the CLI.

## Scope Contract

- Inspection reads public read models or diagnostics summaries and must not
  mutate runs, allocate attempts, acquire leases, schedule retries, clean files,
  emit events, or call executor code.
- `loom.pipeline.reliability` remains import-light and does not import stores,
  diagnostics, CLI, executors, plugins, or service clients.
- Reliability facts stay associated with existing run/stage/attempt/status and
  transaction records. Status enum values remain unchanged.
- Unsupported timeout evidence is exposed as persisted timeout outcomes and
  preflight diagnostics, not as executor log parsing.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_reliability_api.py`,
  `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: public reliability exports and
  import-light boundaries remain intact after diagnostics/CLI additions.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/execution/test_runner.py`,
  `tests/unit/loom/diagnostics/test_diagnostics_inspection.py`,
  `tests/unit/loom/diagnostics/test_backend_diagnostics.py`,
  `tests/unit/loom/cli/test_status_logs.py`,
  `tests/unit/loom/cli/test_backend.py`
- Required assertions or deferral reason: selected policy facts are persisted;
  diagnostics summarize reliability facts; status/backend CLI presentation
  remains read-only and compact.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authoritative_read_model_contract.py`,
  `tests/contracts/test_reliability_contract.py`,
  `tests/contracts/test_store_contract.py`
- Required assertions or deferral reason: reliability record shapes and store
  read facets remain stable.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline`,
  `tests/integration/diagnostics/test_cli_status_logs.py`
- Required assertions or deferral reason: actual runner/authority flows expose
  selected reliability policy and generated retry/timeout facts through
  diagnostics where applicable.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py`,
  `tests/e2e/test_cli_runs_e2e.py`
- Required assertions or deferral reason: existing CLI smoke coverage remains
  compatible with the enriched status payloads.

### Opt-In Suites

- Status: deferred
- Markers affected: no real cluster, container, cloud, network, service,
  telemetry, or optional-SDK markers
- Required assertions or deferral reason: Phase 6 is read-model/diagnostics
  presentation over fake/local authoritative records.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_reliability_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/diagnostics/test_diagnostics_inspection.py tests/unit/loom/diagnostics/test_backend_diagnostics.py tests/unit/loom/cli/test_status_logs.py tests/unit/loom/cli/test_backend.py
uv run pytest tests/contracts/test_authoritative_read_model_contract.py tests/contracts/test_reliability_contract.py tests/contracts/test_store_contract.py
uv run pytest tests/integration/diagnostics/test_cli_status_logs.py
```

Final PR-preparation commands:

```sh
uv run pytest tests/package tests/contracts tests/unit/loom/pipeline tests/unit/loom/diagnostics tests/unit/loom/cli
uv run pytest tests/integration/pipeline tests/integration/diagnostics tests/e2e/test_cli_core.py tests/e2e/test_cli_runs_e2e.py
make validate-pr
make test-summary
```

## Design Impact

- Maintainability: reliability presentation stays in diagnostics/formatting
  helpers and does not leak into executor or store internals.
- Extensibility: Stage 20 can project the same reliability facts into events,
  and Stage 21 can consume transaction/timeout evidence for cleanup planning.
- Future compatibility: no new CLI command namespace is consumed for broader
  reliability controls.
- Domain neutrality: summaries use generic policy, transaction, retry, timeout,
  and status detail vocabulary.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a new `loom reliability` command | Too broad for finalization and risks implying mutating controls exist. |
| Inspect raw store files directly | Violates the authoritative read-model boundary and breaks future remote stores. |
| Rely on runtime metadata alone for policy inspection | Runtime metadata is useful context, but the Stage 19 contract calls for persisted reliability facts. |
| Parse executor logs for unsupported timeout evidence | Timeout support must come from capability diagnostics and timeout outcome records. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Status text shows compact counts, not every record field | Full raw details are already available in JSON/read models | Users need a dedicated human-readable reliability report. |
| Unsupported timeout diagnostics are summarized from persisted outcomes in status | Preflight remains the detailed capability diagnostic surface | Stage 20 event projections need richer unsupported-policy event payloads. |

## Reviewability

- Files and areas to inspect: `src/loom/pipeline/execution/reliability.py`,
  `src/loom/pipeline/execution/runner.py`,
  `src/loom/diagnostics/inspection.py`, `src/loom/diagnostics/backend.py`,
  `src/loom/cli/formatting.py`, CLI/diagnostics/runner tests, and feature docs.
- Scope-control checks: no mutating commands, no executor-owned retry changes,
  no cleanup/deletion behavior, no event-sink behavior, and no service-specific
  integrations.

## Refinement And Review Budget Status

- Phase implementation refinement: available; use only if targeted validation
  or broad validation exposes a concrete implementation/test blocker
- PR review: unused; one automated review pass available
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: completed in this artifact
- Implementation summary: persisted selected reliability policy facts at the
  stage-attempt boundary, added diagnostics summaries for policy facts, status
  details, transactions, retry decisions, timeout outcomes, and unsupported
  timeout evidence, enriched `loom status` and `loom backend inspect` with
  compact read-only reliability presentation, and updated feature docs for
  final Stage 19 behavior and Stage 20/21 deferrals.
- Implementation validation: focused changed-area unit tests passed
  (`55 passed`); broad Phase 6 package/contract/pipeline/diagnostics/CLI unit
  validation passed (`1343 passed`); Phase 6 integration/e2e validation passed
  (`174 passed`). `make validate-pr` passed Ruff, Pyright, default tests
  (`1808 passed, 26 skipped, 18 deselected`), config-extra tests
  (`447 passed, 1845 deselected`), and package build. `make test-summary`
  passed package (`102 passed, 1 skipped`), unit (`1276 passed, 7 skipped,
  1 deselected`), contract (`256 passed, 2 skipped`), integration
  (`159 passed, 8 skipped, 13 deselected`), e2e (`43 passed, 2 deselected`),
  and config-extra (`447 passed, 1845 deselected`).
- Refinement summary: not needed as a separate formal pass; targeted
  validation findings were resolved directly during implementation before the
  implementation commit.
- Blocker-resolution summary: not needed at plan time
- PR preparation: completed with
  `docs/roadmap/stage-19/phases/reliability-inspection-finalization-pr-body.md`;
  PR pending
- Merge summary: pending
- Stack maintenance: pending
- Remaining blockers: none
