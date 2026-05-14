# Phase 1 Execution Plan: Portable Exchange And Bundle Manifest Contracts

## Metadata

- Status: final phase execution plan
- Feature focus: Portable Run Exchange
- PR title: `Portable Run Exchange - Phase 1: Contract And Manifest Models`
- Branch: `codex/portable-run-exchange-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/portable-run-exchange-contracts`
- Phase execution plan path: `docs/roadmap/stage-12/phases/portable-run-exchange-contracts.md`
- Full plan: `docs/roadmap/stage-12/implementation-plan.md`
- Source phase: Phase 1, Portable Exchange And Bundle Manifest Contracts
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR validation, automated review, CI, and target-branch verification
- Workflow path: expanded path
- Successor dependency notes: Phase 2 must build export/archive behavior on these protocol and model contracts without redefining adapter call shapes.
- Plan quality gate: passed on 2026-05-14 in the implementation plan
- Plan quality gate loop budget: review used, refinement used, confirmation used
- Draft pass: completed by managing Codex
- Refine pass: included in this scope-complete expanded-path plan; no separate refinement pass needed unless implementation discovers a contract blocker
- Setup limitations: remote sync was not required for local worktree creation; GitHub auth and remote PR setup remain PR-preparation obligations
- Blockers: none

## Objective

Establish import-light portable-run exchange records, local bundle manifest records, shared result/diagnostic/readiness models, and minimal importer/exporter protocols without archive I/O, authority mutation, queue behavior changes, or CLI commands.

## Full-Plan Context

Phase 1 creates the contracts that later phases use. Phase 2 will materialize local bundle export and inspect behavior, Phase 3 will implement bundle and offline-evidence import alignment, Phase 4 will add transfer evidence and fake/unsupported conformance, and Phase 5 will expose CLI/docs/hardening. This phase must not implement archive read/write, import into run collections, transfer handlers, or CLI behavior.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: all earlier Stage 12 phases are pending, and the local `develop` branch contains the Stage 12 planning and implementation-plan artifacts
- Retarget/rebase plan after predecessor merge: not applicable for Phase 1; successors should branch from `develop` after Phase 1 merges, or from this branch if a GitHub-side merge blocker requires stacking
- Branch cleanup constraints: branch can be deleted after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: define adapter-neutral portable-run exchange contracts, local bundle manifest contracts, result/readiness/diagnostic shapes, and minimal importer/exporter protocols.
- Required scope: public or import-light value models, strict manifest model and version handling, adapter identity, selected entries and payload refs, diagnostics, import/export/inspection/readiness/result envelopes, unsupported diagnostics, and package-boundary guardrails.
- Required checkpoints: prove plain-data round trips, unsupported schema diagnostics, explicit extension fields, import-light placement, and stable protocol signatures for later adapters.
- Acceptance criteria: local bundle and offline evidence can both map into portable-run records without either becoming the other's storage format, and lower layers do not import archive/catalog behavior.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/runs/models.py` owns public run-catalog dataclasses and lightweight validation helpers; `src/loom/runs/__init__.py` has a strict `__all__`; `src/loom/authority/offline_import.py` currently defines offline import diagnostics/results; `src/loom/queue/models.py` accepts plain `delegated_verification`; `src/loom/serialization` provides plain-data helpers.
- Existing tests or harness behavior: `tests/package/test_runs_api.py` locks `loom.runs.__all__` and lightweight import behavior; `tests/package/test_import_boundaries.py` covers root, queue, authority, and subsystem import boundaries; `tests/contracts/test_offline_import_contract.py` and `tests/contracts/test_queue_records_contract.py` lock existing result/evidence shapes.
- Import-boundary or dependency constraints: neutral exchange models must not import CLI, stores, archive helpers, queue controllers, authority repositories, pipeline execution, optional config dependencies, or project code.

## In-Scope Work

- Add import-light portable exchange models under `loom.runs` or a small adjacent import-light module if boundary tests require it.
- Add strict local bundle manifest models with schema version, kind, entry records, payload selection, checksums, warnings, and explicit extension fields.
- Add shared diagnostics, adapter identity, export/inspection/import result envelopes, transfer evidence placeholders, and migration-readiness records.
- Add minimal `RunExporter` and `RunImporter` protocols over these records.
- Export the public contract from `loom.runs` while preserving cheap imports.
- Add unit, contract, and package tests for serialization, validation, unsupported diagnostics, protocol signatures, and import boundaries.

## Out-of-Scope Work

- Archive read/write, extraction, checksum verification over archive members, or temporary staging.
- Exporting completed runs from stores or catalog state.
- Importing bundles into run collections or authority.
- Offline import behavior changes beyond optionally adding adapter-result conversion helpers that preserve current contracts.
- Queue consumption/display changes.
- CLI commands or formatting.
- Concrete external providers, transfer handlers, plugin loading, or live migrated resume.

## Assumptions

- `loom.runs` remains the public owner for the contract as long as package tests prove it remains lightweight.
- Manifest top-level fields are strict, while `extensions` is the only open-ended field for future opaque data.
- Protocols should be structural and minimal; later phases may implement adapters but must not widen call shapes without recording a compatibility reason.

## Scope Contract

The phase must define plain-data records with deterministic `to_dict` and `from_dict` behavior for persisted or public shapes. Unknown manifest fields must be rejected with a structured diagnostic or schema error, not silently ignored. Adapter-neutral records must model source identity, target identity policy, selected entries, payload refs, diagnostics, adapter identity, result status, readiness blockers, and unsupported behavior without depending on local bundle archive internals. `RunExporter` and `RunImporter` are callable protocols only; they do not imply plugin discovery, automatic dispatch, network clients, or provider-specific adapters.

## Design Impact

- Maintainability: centralizes contract vocabulary before archive/import implementation, keeping later phases from inventing divergent result shapes.
- Extensibility: leaves adapter protocols and extension fields ready for later provider and remote-artifact stages without committing to their behavior.
- Domain neutrality: records describe runs, stages, artifacts, payload refs, diagnostics, and transfer evidence only; no dataset/model/report semantics.
- Source-tree boundaries: `loom.runs` may expose the public surface, but import-light records must not pull in catalog scanning, SQLite, authority repository, queue controllers, CLI, stores, or optional dependencies.

## Future Compatibility

Stage 14 plugin discovery and later external providers can implement the protocols. Stage 15/16 remote or external artifacts can attach semantics to opaque refs and extension fields. Future live migration can consume readiness blockers only after target authority equivalence, artifact rebasing, and planner reuse policy are designed.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Make local bundles the base provider protocol | It would leak archive layout into offline evidence and future providers. |
| Put contracts in CLI or stores | CLI must stay a wrapper and stores should remain authority/materialization owners. |
| Permit unknown manifest top-level fields | It weakens fail-closed inspection/import behavior. |
| Force offline evidence to serialize as a bundle | It would blur the v10 authority-owned strict import adapter boundary. |
| Add concrete provider stubs | Real providers, plugin discovery, and network handlers are out of scope for v12 Phase 1. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Minimal protocols may be narrower than future providers need | No concrete external adapter exists in v12, so widening now would be speculative. | Stage 14 plugin discovery or a real provider adapter needs additional fields or lifecycle hooks. |
| Readiness records ship before live migration | Future migration needs stable blocker vocabulary, but v12 must not enable resume. | Target-store equivalence, artifact rebasing, and continuation policy are designed. |

## Reviewability

- Expected PR size and shape: focused model/protocol/test PR with no archive I/O or CLI behavior.
- Files and areas to inspect: `src/loom/runs`, possible import-light adjacent module, `tests/package`, `tests/unit` or model tests, and `tests/contracts`.
- Scope-control checks: no archive helper implementation, no CLI registration, no authority mutation, no queue parsing, no optional dependency imports, and no provider-specific clients.

## Implementation Steps

1. Add portable exchange, manifest, diagnostic, readiness, and result dataclasses with strict validation and plain-data serialization.
2. Add minimal importer/exporter protocols and unsupported adapter diagnostic helpers.
3. Export the public contract from `loom.runs` while preserving current catalog API compatibility.
4. Add unit and contract coverage for round trips, strict manifest fields, readiness blockers, unsupported diagnostics, and protocol conformance fixtures.
5. Add or extend package import-boundary tests for `loom.runs`, authority/offline import, queue, stores, CLI, plugins, and optional dependencies.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `loom.runs` exports the new contract intentionally and remains lightweight; authority, queue, stores, CLI, plugins, and optional dependencies do not import archive/catalog behavior through neutral records.

### Unit Suite

- Status: required
- Expected paths: model-focused tests under `tests/unit/runs/` or the closest existing unit-test convention
- Required assertions or deferral reason: validation, serialization, manifest version handling, strict top-level field rejection, extension-field preservation, readiness blocker codes, and diagnostic records.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_run_exchange_contract.py` or equivalent
- Required assertions or deferral reason: plain-data record compatibility for local bundle, offline-evidence, fake, and unsupported adapter records; minimal importer/exporter protocol signatures and result envelopes.

### Integration Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: Phase 1 has no archive I/O, import, export, or queue runtime behavior; package smoke tests cover cheap imports.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: CLI and workflow behavior starts in Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no network, cluster, plugin, or external provider behavior is in scope.

## Risks

- Public model surface could grow too broad before concrete adapters exist.
- Placing neutral models inside `loom.runs` could accidentally import catalog/archive dependencies into authority or queue.
- Result names could overlap awkwardly with existing offline import result names; compatibility shims must not break v10 contracts.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py tests/contracts/test_run_exchange_contract.py
uv run pytest tests/unit/runs
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: model/protocol definitions first, then public exports, then tests, then package-boundary hardening.
- Tests to run with each slice: run targeted unit/contract tests after models, then package boundary tests after public exports.
- Decisions the executor must not revisit: no archive I/O, no CLI commands, no authority mutation, no queue behavior change, no provider-specific adapters, no live migration.
- Conditions that require stopping for the manager: import-boundary failure that cannot be solved by moving neutral records to an import-light module, need to widen importer/exporter protocols beyond the plan, or conflict with existing offline import public contracts.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in the Phase 1 worktree.
- Final phase execution plan: completed; no separate refinement pass used.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
