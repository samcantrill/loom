# Phase 4 Execution Plan: Transfer Evidence And Protocol Conformance

## Metadata

- Status: final phase execution plan
- Feature focus: Portable Run Exchange
- PR title: `Portable Run Exchange - Phase 4: Transfer Evidence Protocols`
- Branch: `codex/transfer-evidence-protocols`
- Worktree: `/home/samcantrill/work/loom-worktrees/transfer-evidence-protocols`
- Phase execution plan path: `docs/roadmap/stage-12/phases/transfer-evidence-protocols.md`
- Full plan: `docs/roadmap/stage-12/implementation-plan.md`
- Source phase: Phase 4, Transfer Evidence And Importer/Exporter Protocols
- Stack predecessor: none; Phase 3 merged to `develop`
- Base branch: `develop` via `origin/develop` at `dc710962527a290ec29c66aaa724bc689e686b91`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR validation, automated review, CI, and target-branch verification
- Workflow path: fast path
- Successor dependency notes: Phase 5 CLI/docs can cite public transfer evidence helpers but must not implement providers or queue archive parsing.
- Plan quality gate: passed on 2026-05-14 in the implementation plan
- Plan quality gate loop budget: review used, refinement used, confirmation used
- Draft pass: completed by managing Codex
- Refine pass: not needed; scope is contract-heavy and does not widen public protocols
- Setup limitations: none; branch/worktree created from updated `origin/develop`
- Blockers: none

## Objective

Publish queue-consumable transfer verification helpers and prove fake,
unsupported, and structured adapter behavior over the existing Phase 1
`RunExporter` and `RunImporter` protocols without adding concrete transfer
providers.

## Full-Plan Context

Phase 1 added transfer verification records and importer/exporter protocols.
Phases 2 and 3 implemented local bundle export/import and offline-evidence
alignment. Phase 4 must bridge transfer evidence into existing queue delegated
verification mappings while preserving the core design rule that queue consumes
plain evidence, not bundle archives or provider internals.

## Stack Context

- Root or stacked phase: root phase after Phase 3 merge
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 3 PR #148 is merged and post-merge metadata is pushed to `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: branch can be deleted after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: transfer evidence mappings, fake protocol conformance, unsupported
  transfer/provider diagnostics, and queue-safe delegated verification shape.
- Required scope: public helper functions over `TransferVerificationRecord`,
  queue formatting preservation of `proven`, `unproven`, and `unsupported`
  statuses, fake importer/exporter contract tests, and unsupported diagnostic
  tests.
- Required checkpoints: no concrete SSH/object-store/provider implementations,
  no queue dependency on local bundle archive helpers, no protocol widening.
- Acceptance criteria: queue/delegated-launch surfaces can reference transfer
  evidence as plain mappings; unsupported transfer/provider behavior is
  explicit; package boundaries remain clean.

## Current Source And Harness Findings

- `src/loom/runs/models.py` already owns `TransferVerificationRecord`,
  `TransferVerificationCheck`, `TransferVerificationStatus`,
  `UnsupportedTransferRecord`, and the `RunExporter`/`RunImporter` protocols.
- `LaunchContract.delegated_verification` already accepts arbitrary plain
  mappings; `src/loom/queue/slurm.py` renders delegated verification evidence
  without importing run bundle code.
- The current SLURM verification formatter preserves `proven` and `unproven`
  states but collapses unknown structured statuses to `unproven`; Phase 4 must
  preserve `unsupported`.
- Existing package import-boundary tests cover queue and `loom.runs` import
  lightness; this phase should extend those guarantees rather than add new
  runtime dependencies.

## In-Scope Work

- Add public `loom.runs` helpers that build unsupported transfer diagnostics,
  unsupported transfer verification records, and queue/delegated-verification
  plain mappings from `TransferVerificationRecord`.
- Preserve `unsupported` check status in delegated queue verification reports
  and include an `unsupported` list plus summary count.
- Add fake exporter/importer contract coverage using the existing Phase 1
  protocols.
- Add unsupported transfer/provider contract and unit tests using structured
  diagnostics and `UnsupportedTransferRecord`.
- Update package API tests for any new public helper exports.

## Out-of-Scope Work

- SSH, object-store, remote workspace, network, provider, or plugin adapters.
- Automatic exporter/importer dispatch.
- Queue-owned bundle schemas or queue parsing of bundle archives.
- CLI commands or formatting.
- Widening the Phase 1 importer/exporter protocol methods.

## Assumptions

- A launch-contract delegated verification mapping can carry one named
  transfer-verification item whose details include the full
  `TransferVerificationRecord` dictionary.
- Queue adapters should preserve unsupported evidence status but do not need to
  understand provider-specific details.
- Explicit structured unsupported diagnostics are sufficient for v12; concrete
  transfer handlers remain future work.

## Scope Contract

The phase may add public helper functions and queue formatting support for
plain evidence mappings. It must not import bundle archive helpers into queue
modules, add provider implementations, or alter the `RunExporter` and
`RunImporter` protocol signatures.

## Design Impact

- Maintainability: transfer evidence helpers centralize plain-data conversion
  rather than duplicating ad hoc mapping shapes in queue or future CLI code.
- Extensibility: future providers can populate the same verification records
  and delegated verification mapping without changing queue dispatch.
- Domain neutrality: evidence remains generic adapter/check/status data.
- Source-tree boundaries: `loom.runs` owns transfer records; `loom.queue`
  consumes plain mappings only.

## Future Compatibility

Later provider adapters can emit `TransferVerificationRecord` values and pass
their delegated mapping through queue launch contracts. Phase 5 CLI can display
the same result evidence without knowing provider internals.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Queue imports `loom.runs` transfer helpers | It would couple queue dispatch to run exchange internals. |
| Queue parses bundle archive metadata | The stage requires queue to consume evidence, not archives. |
| Add concrete fake provider runtime modules | Contract-local fake adapters are enough to prove protocols. |
| Treat unsupported as unproven | Unsupported is a distinct contract status and should remain visible. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Transfer handlers remain unsupported | v12 only defines result/evidence contracts. | A later stage selects SSH, object-store, or provider behavior. |
| Delegated verification mapping uses a single named evidence item by default | It avoids queue schema changes while preserving details. | Queue records gain first-class transfer evidence fields. |

## Reviewability

- Expected PR size and shape: one small helper module/export update, one narrow
  queue formatting change, and focused unit/contract/package tests.
- Files and areas to inspect: `src/loom/runs`, `src/loom/queue/slurm.py`,
  `tests/unit/loom/runs`, `tests/unit/loom/queue`,
  `tests/contracts`, and `tests/package`.
- Scope-control checks: no provider implementations, no network, no CLI, no
  protocol widening, no queue archive parsing.

## Implementation Steps

1. Add transfer evidence helper functions and public exports under `loom.runs`.
2. Preserve `unsupported` statuses in delegated queue verification reports.
3. Add unit tests for transfer evidence mapping and queue unsupported status
   preservation.
4. Add contract tests for fake importer/exporter conformance and unsupported
   transfer/provider diagnostics.
5. Run targeted package/unit/contract checks, then final `make validate-pr` and
   `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new public exports remain stable and
  queue modules still do not import local bundle archive helpers.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/runs/test_transfer_evidence.py`,
  `tests/unit/loom/queue/test_slurm_adapter.py`
- Required assertions or deferral reason: transfer verification mapping
  preserves proven/unproven/unsupported status and queue reports retain
  unsupported evidence.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_transfer_evidence_contract.py`,
  `tests/contracts/test_run_exchange_contract.py`,
  `tests/contracts/test_queue_records_contract.py`
- Required assertions or deferral reason: fake importer/exporter conformance,
  unsupported transfer/provider diagnostics, and queue-consumable evidence
  shapes.

### Integration Suite

- Status: deferred
- Expected paths: none unless a queue formatting integration gap appears
- Required assertions or deferral reason: no runtime transfer handler behavior
  changes are in scope.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: CLI workflow starts in Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no network, cluster, plugin, or
  external provider behavior is in scope.

## Risks

- Evidence helpers could accidentally define provider semantics instead of
  neutral verification records.
- Queue formatting changes could disrupt existing delegated SLURM evidence.
- Unsupported diagnostics could be mistaken for a dispatch implementation.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/runs/test_transfer_evidence.py tests/unit/loom/queue/test_slurm_adapter.py tests/contracts/test_transfer_evidence_contract.py tests/contracts/test_run_exchange_contract.py tests/contracts/test_queue_records_contract.py tests/package/test_runs_api.py tests/package/test_import_boundaries.py
uv run ruff check src/loom/runs src/loom/queue/slurm.py tests/unit/loom/runs/test_transfer_evidence.py tests/unit/loom/queue/test_slurm_adapter.py tests/contracts/test_transfer_evidence_contract.py
uv run --extra config pyright src/loom/runs src/loom/queue/slurm.py tests/unit/loom/runs/test_transfer_evidence.py tests/unit/loom/queue/test_slurm_adapter.py tests/contracts/test_transfer_evidence_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Keep helpers pure and plain-data oriented.
- Queue changes should consume only the delegated verification mapping already
  present on `LaunchContract`.
- Preserve existing `proven` and `unproven` behavior while adding
  `unsupported`.
- Conditions that require stopping for the manager: need for a provider
  implementation, queue archive parsing, or protocol signature widening.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in the Phase 4 worktree.
- Final phase execution plan: completed; fast path selected.
- Implementation summary: added public `loom.runs` transfer evidence helpers,
  unsupported transfer diagnostics/records, queue delegated-verification
  preservation for `unsupported` statuses, and fake/unsupported
  importer/exporter contract coverage.
- Implementation validation: targeted Ruff passed; targeted Pyright passed;
  targeted pytest passed with 61 tests; `make validate-pr` passed with Ruff,
  Pyright, default pytest, config-extra pytest, and build success; `make
  test-summary` passed with package 77 passed, unit 1051 passed, contract 179
  passed, integration 148 passed, e2e 41 passed, and config-extra 438 passed.
- Refinement summary: no separate implementation refinement pass used; targeted
  fixes were completed during the implementation pass before full validation.
- Blocker-resolution summary: 0/3 blocker-resolution passes used.
- PR preparation: PR body prepared in
  `docs/roadmap/stage-12/phases/transfer-evidence-protocols-pr-body.md`;
  PR open/verification pending.
- Stack maintenance: none required; Phase 4 is a root phase targeting
  `develop`.
- Remaining blockers: none.
