# Phase 14 Execution Plan: Diagnostics, Preflight, And Read-Only Source Labeling

## Metadata

- Status: phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 14: Diagnostics, Preflight, And Read-Only Source Labeling`
- Branch: `codex/authority-diagnostics-labeling`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-diagnostics-labeling`
- Phase execution plan path: `docs/phases/authority-diagnostics-labeling.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 14 - Diagnostics, Preflight, And Read-Only Source Labeling
- Stack predecessor: none; Phase 13 merged in PR #131 and is recorded in the plan
- Base branch: `develop` at `775fdb0`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: not needed before implementation; the source inventory identifies additive read-only labels and no unresolved design fork
- Blockers: none; implementation may begin from this phase execution plan.

## Objective

Make read-only diagnostics, preflight, and catalog/status output explicit about which state source is being displayed, whether that source is authoritative, and what online/offline policy applies, without adding mutation APIs or weakening Phase 13 fail-closed behavior.

## Source Findings

- `diagnostics.inspection.inspect_run_status()` already rejects local-only lifecycle state and prefers `read_authoritative_run()` when authority is present, but returned summaries do not expose that the status/stage/submitted-operation state came from authority truth.
- Artifact and log inspection still read local materialized files; those surfaces need local-materialization labels so they do not look like lifecycle authority truth.
- `diagnostics.backend.inspect_backend()` and `inspect_backend_capabilities()` already use read-only authority APIs and have mutation-trap coverage, but the result payloads only expose backend name/schema/revision and not source/policy facts.
- `diagnostics.preflight` has stable check IDs, so Phase 14 should enrich existing check details rather than introduce a new check group unless unavoidable.
- `runs._scan` already differentiates authority-backed summaries, registry/marker failures, and local lifecycle unsupported warnings. The public catalog model needs additive source labels on summaries and warning details.
- CLI text formatting for status, backend, runs, and preflight is concise and can include one-line source labels without changing command structure.

## In Scope

- Add a small shared read-only source-label model/helper for authoritative service truth, registry hints, materialized local state, deferred-finalization state, offline evidence, and unknown/unavailable authority.
- Add source labels to backend diagnostics result payloads and text output.
- Add source labels to run status, submitted operation, stage status, artifact, and log summaries where those summaries display persisted state.
- Add source labels to run catalog summaries and relevant catalog warning details.
- Enrich existing preflight check details with authority selection, state source, online/offline policy, and guidance where the check reads or reasons about persisted run state.
- Improve guidance for missing/unavailable authority without mutating local state or scanning local lifecycle state as current authority truth.
- Add focused unit/contract/integration coverage for representative labels and preserve existing schema compatibility with additive fields only.

## Out Of Scope

- New mutation APIs or authority lifecycle behavior.
- Workspace coordination service migration.
- Offline evidence writer or import transaction.
- Resource admission leases.
- External-process diagnostics beyond default deterministic tests.
- Broad UX redesign or compacting label wording.

## Assumptions

- Additive JSON fields are acceptable for existing CLI/result schemas; schema version bumps are not required unless tests expose a contract that forbids additive fields.
- Authority-backed local and in-memory test stores may stand in for service-owned read semantics, while source labels still use generic authority truth wording rather than production-service claims.
- Offline evidence labels can be represented now as a durable vocabulary even though Phase 17 and Phase 18 implement evidence writing/import later.
- Preflight check IDs remain stable; details payloads are the extension point for Phase 14.

## Scope Contract

This phase may edit diagnostics models/helpers, backend/preflight/inspection code, run-catalog models/scanning, CLI formatting/tests for read-only labels, and affected docs/examples. It must not add mutation methods, change run execution behavior, implement offline evidence import, or introduce server-private repository imports into runtime clients.

## Design Impact

- Maintainability: centralizes source-label vocabulary instead of scattering free-form strings across CLI surfaces.
- Extensibility: reserves durable labels for future hosted authorities, deferred finalization, offline evidence, and registry hints.
- Reviewability: labels are additive plain-data fields and short text lines, with tests focused on representative surfaces.
- Safety: read-only paths remain read-only and unavailable authority is reported as unavailable rather than silently downgrading authoritative lifecycle state to local files.

## Future Compatibility

The label vocabulary should be reusable by Phase 17 offline evidence and Phase 18 import so imported runs can be described without retrofitting status/catalog contracts again.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a new preflight group/check ID for authority diagnostics | Stable check IDs already exist; enriching details avoids unnecessary public surface churn. |
| Only update CLI text and not JSON payloads | Machine consumers also need to distinguish authority truth from local evidence. |
| Let catalog/status fall back to local lifecycle state when authority is unavailable | That would undo v10 fail-closed semantics and could show stale state as current truth. |
| Encode source labels as unconstrained strings everywhere | A shared helper keeps labels consistent and testable. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Labels may be verbose in text output | Correct semantics matter more than compact formatting for this UX debt phase. | A later UX pass has enough usage feedback to compact labels. |
| Offline evidence labels are vocabulary-only before evidence exists | Future phases need stable terms but should not implement evidence early. | Phase 17 or Phase 18 wires real offline evidence data. |

## Reviewability

- Files to inspect: `src/loom/diagnostics/source_labels.py`, `src/loom/diagnostics/inspection.py`, `src/loom/diagnostics/backend.py`, `src/loom/diagnostics/preflight.py`, `src/loom/runs/models.py`, `src/loom/runs/_scan.py`, `src/loom/cli/formatting.py`, and focused tests.
- Scope-control checks: no mutation calls added to diagnostics, no private authority repository imports in read-only CLI clients, and no offline import/evidence writer implementation.

## Implementation Steps

1. Add shared source-label value helpers that produce plain-data mappings for authoritative service truth, registry hints, local materialization, deferred finalization, offline evidence, and unavailable authority.
2. Add additive source fields to diagnostics inspection summaries and populate them for authoritative status, local artifacts, and logs.
3. Add source/policy facts to backend diagnostics and backend capabilities payloads plus concise CLI text lines.
4. Enrich preflight run/artifact/SLURM active-submission checks with state-source and authority-policy details.
5. Add source labels to run catalog summaries and relevant warning details from direct scans.
6. Update CLI text formatting and representative tests across diagnostics, backend, preflight, status, and runs.
7. Run targeted Ruff, Pyright, unit/contract/integration suites, then `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: diagnostics and catalog read-only helpers do not import private authority repository modules or server implementation details.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/diagnostics/test_diagnostics_inspection.py`, `tests/unit/loom/diagnostics/test_backend_diagnostics.py`, `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`, `tests/unit/loom/cli/test_status_logs.py`, `tests/unit/loom/cli/test_backend.py`, `tests/unit/loom/cli/test_preflight.py`, `tests/unit/loom/cli/test_runs.py`, `tests/unit/loom/runs/test_direct_scan_helpers.py`
- Required assertions or deferral reason: source-label serialization, text formatting, local versus authoritative classification, preflight guidance, and catalog warning details.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_backend_diagnostics_contract.py`, `tests/contracts/test_diagnostics_preflight_contract.py`, `tests/contracts/test_cli_preflight_contract.py`, `tests/contracts/test_cli_runs_contract.py`, `tests/contracts/test_run_catalog_contract.py`
- Required assertions or deferral reason: public payloads remain plain-data compatible and stable with additive source-label fields.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/test_cli_status_logs.py`, `tests/integration/diagnostics/test_cli_preflight.py`, `tests/integration/diagnostics/test_diagnostics_preflight_integration.py`, `tests/integration/pipeline/test_backend_diagnostics.py`, `tests/integration/pipeline/test_cli_runs.py`, `tests/integration/pipeline/test_run_catalog_current_list.py`, `tests/integration/pipeline/test_run_catalog_direct_scan.py`
- Required assertions or deferral reason: CLI/read-model surfaces expose source labels against deterministic authority-backed stores and remain read-only.

### E2E Suite

- Status: optional
- Expected paths: existing CLI smoke tests when touched by formatting.
- Required assertions or deferral reason: Phase 14 primarily changes unit/contract/integration read-only output; no external-process diagnostics are required.

### Opt-In Suites

- Status: deferred
- Markers affected: external authority process and real scheduler diagnostics.
- Required assertions or deferral reason: default validation must remain deterministic and not require a real hosted authority or SLURM cluster.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/diagnostics src/loom/cli/backend.py src/loom/cli/status.py src/loom/cli/runs.py src/loom/cli/formatting.py src/loom/runs tests/unit/loom/diagnostics tests/unit/loom/cli/test_status_logs.py tests/unit/loom/cli/test_backend.py tests/unit/loom/cli/test_preflight.py tests/unit/loom/cli/test_runs.py tests/unit/loom/runs/test_direct_scan_helpers.py tests/contracts/test_backend_diagnostics_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py tests/contracts/test_cli_runs_contract.py tests/contracts/test_run_catalog_contract.py tests/integration/diagnostics tests/integration/pipeline/test_backend_diagnostics.py tests/integration/pipeline/test_cli_runs.py tests/integration/pipeline/test_run_catalog_current_list.py tests/integration/pipeline/test_run_catalog_direct_scan.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/diagnostics src/loom/cli/backend.py src/loom/cli/status.py src/loom/cli/runs.py src/loom/cli/formatting.py src/loom/runs tests/unit/loom/diagnostics tests/unit/loom/cli/test_status_logs.py tests/unit/loom/cli/test_backend.py tests/unit/loom/cli/test_preflight.py tests/unit/loom/cli/test_runs.py tests/unit/loom/runs/test_direct_scan_helpers.py tests/contracts/test_backend_diagnostics_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py tests/contracts/test_cli_runs_contract.py tests/contracts/test_run_catalog_contract.py tests/integration/diagnostics tests/integration/pipeline/test_backend_diagnostics.py tests/integration/pipeline/test_cli_runs.py tests/integration/pipeline/test_run_catalog_current_list.py tests/integration/pipeline/test_run_catalog_direct_scan.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/diagnostics tests/unit/loom/cli/test_status_logs.py tests/unit/loom/cli/test_backend.py tests/unit/loom/cli/test_preflight.py tests/unit/loom/cli/test_runs.py tests/unit/loom/runs/test_direct_scan_helpers.py tests/contracts/test_backend_diagnostics_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py tests/contracts/test_cli_runs_contract.py tests/contracts/test_run_catalog_contract.py tests/integration/diagnostics tests/integration/pipeline/test_backend_diagnostics.py tests/integration/pipeline/test_cli_runs.py tests/integration/pipeline/test_run_catalog_current_list.py tests/integration/pipeline/test_run_catalog_direct_scan.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: used by managing-agent bounded validation fix after `make validate-pr` exposed one stale catalog-model serialization assertion
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Implementation summary: added shared plain-data source-label helpers; labeled backend diagnostics, capabilities, status/stage/submitted-operation summaries, artifact/log summaries, preflight details, run catalog summaries, and catalog warnings; added concise CLI source output and representative unit, contract, and integration assertions. Runtime behavior remains read-only and mutation paths are unchanged.
- Validation so far:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...` passed for touched diagnostics, CLI, run-catalog, unit, contract, and integration paths.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright ...` passed for the same focused paths.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest ...` passed for the combined Phase 14 focused slice: 115 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_cli_runs_contract.py tests/contracts/test_run_catalog_contract.py tests/integration/pipeline/test_cli_runs.py tests/integration/pipeline/test_run_catalog_current_list.py tests/integration/pipeline/test_run_catalog_direct_scan.py tests/unit/loom/runs/test_direct_scan_helpers.py` passed: 20 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py` passed: 34 passed.
  - The non-extra focused pytest command against optional config diagnostics was superseded by the `--extra config` run because those tests require the config extra.
  - Initial `make validate-pr` failed only on `tests/unit/loom/runs/test_run_catalog_models.py::test_run_summary_uses_run_uri_and_plain_serialization`; the assertion was updated to verify additive `state_source` serialization for run, stage, artifact, and submitted-operation summaries. Focused reruns of Ruff, Pyright, and that unit file passed.
- Stack maintenance: none yet; this is a root phase branch targeting `develop`.
