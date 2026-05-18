# Phase 1 Execution Plan: Cleanup Records, Retention, Selectors, And Safety Contracts

## Metadata

- Status: final phase execution plan
- Feature focus: Cleanup And Retention
- PR title: `Cleanup And Retention - Phase 1: Records And Safety Contracts`
- Branch: `codex/cleanup-records-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-records-contracts`
- Phase execution plan path: `docs/roadmap/stage-21/phases/cleanup-records-contracts.md`
- Full plan: `docs/roadmap/stage-21/implementation-plan.md`
- Source phase: Phase 1, `cleanup-records-contracts`
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase; eligible for merge to `develop` after automated review, validation, CI, and PR target checks pass
- Workflow path: expanded path
- Successor dependency notes: Phase 2 branches from this phase only if this PR cannot be merged before Phase 2 starts.
- Plan quality gate: passed in the implementation plan on 2026-05-18
- Plan quality gate loop budget: consumed by recorded review/refinement/confirmation; no blockers remain
- Draft pass: completed locally in this artifact
- Refine pass: completed locally in this artifact because Phase 1 introduces public records and safety contracts
- Setup limitations: none
- Blockers: none

## Objective

Add the import-light cleanup value records, selector helpers, retention helpers, and local path-safety decisions that later cleanup planning and deletion phases can reuse without introducing authority mutations, filesystem deletion, events, collection GC, or CLI behavior.

## Full-Plan Context

This phase creates the public cleanup contract vocabulary for Stage 21. Phase 2 will read authoritative cleanup candidates into dry-run reports and persistence scaffolding, Phase 3 will add explicit deletion and events, Phase 4 will add collection GC and preflight warnings, and Phase 5 will add CLI/docs. Those future behaviors must remain out of scope here.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: all earlier phases are absent and the implementation plan targets `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: branch can be deleted after merge if no successor branch depends on it

## Source Phase Summary

- Goal: add cleanup records, retention, selectors, and safety contracts.
- Required scope: `loom.pipeline.cleanup`, `loom.artifacts`, and package/unit/contract tests.
- Required checkpoints: public imports are intentional and cheap; records are plain-data-compatible; safety helpers reject rather than repair; selectors are bounded and explainable.
- Acceptance criteria: deterministic selector/safety reports, no deletion or persistence, domain-neutral tests, and no provider-specific semantics.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/read_models.py` already defines `CleanupCandidate`, `CleanupCandidateKind`, `MaterializedRef`, and `MaterializedRefKind`; Phase 1 should build cleanup-facing wrappers around these rather than changing persistence.
- Existing tests or harness behavior: package tests cover import boundaries, contract tests cover store/read-model serialization, and artifact contract tests cover plain-data retention maps on published artifacts.
- Import-boundary or dependency constraints: cleanup records and retention helpers must not import CLI, diagnostics, concrete executors, provider SDKs, or project packages.

## In-Scope Work

- Create `loom.pipeline.cleanup` with public exports for records, selectors, safety helpers, and cleanup-specific errors.
- Define plain-data cleanup records for targets, managed roots, selection explanations, report entries, reports, result entries/results, and structured delete intent.
- Add bounded selector normalization/matching across cleanup candidate facts and optional plain metadata fields.
- Add `RetentionMode` and `RetentionPolicy` helpers in `loom.artifacts` without changing retention into automatic deletion policy.
- Add local path-safety decisions for trusted managed roots, ownership evidence, outside-root paths, symlinks, symlink traversal, missing paths, and unsupported non-local refs.
- Add package, unit, and contract tests for the new public contracts.

## Out-of-Scope Work

- Authority schema or backend persistence changes.
- Dry-run planning over actual stores.
- Filesystem deletion.
- Cleanup event projection or sink dispatch.
- Collection GC, diagnostics/preflight integration, and CLI commands.
- Whole-run deletion, remote/provider deletion, arbitrary query language, and automatic retention enforcement.

## Assumptions

- Existing `CleanupCandidate` fields are sufficient for Phase 1 selector tests.
- Later phases can add authority-backed managed-root facts without changing the Phase 1 safety decision shape.
- Retention metadata remains a generic plain-data hint and does not prove ownership or eligibility by itself.

## Scope Contract

Public cleanup records must be immutable dataclasses or enums with stable `to_dict`/`from_dict` behavior, strict unknown-field rejection, and plain-data validation. Selectors are bounded fields rather than expressions. Safety helpers accept trusted managed-root records and target records, return explicit decisions with reason codes, and never delete, create, chmod, normalize into arbitrary roots, or follow symlinks for approval.

## Design Impact

- Maintainability: centralizes cleanup vocabulary in one package so later CLI, diagnostics, authority, and collection work reuse one policy layer.
- Extensibility: leaves future adapters and whole-run cleanup room to add target capabilities without redesigning selector/result records.
- Domain neutrality: records use generic candidate, target, retention, and path terms only.
- Source-tree boundaries: runtime code remains under `src/loom`, phase artifact under `docs/roadmap`, and tests mirror package/unit/contract suites.

## Future Compatibility

- Phase 2 can append report facts using the same report records.
- Phase 3 can persist result facts and project events using the same result records.
- Future remote deletion can report unsupported targets now and later add capability-gated adapters without changing selector semantics.
- Future whole-run deletion must add stronger gates and tombstones instead of overloading candidate cleanup records.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put cleanup safety in CLI handlers | Would duplicate policy and make Python API behavior weaker than CLI behavior. |
| Use arbitrary selector expressions | Conflicts with the confirmed bounded selector requirement and makes safety explanations harder to review. |
| Treat retention hints as deletion policy | Stage 21 explicitly makes retention inspectable metadata only. |
| Accept broad input paths as managed roots | Design-safety review requires trusted roots from authority/store/config facts, not presentation inputs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Phase 1 safety helpers require callers to provide trusted managed roots. | Authority-backed root discovery lands in Phase 2. | If later phases cannot prove roots without expanding the root record shape. |
| Selector set starts small and field-based. | Bounded selectors are the confirmed first implementation. | Users need compound boolean cleanup policy. |

## Reviewability

- Expected PR size and shape: moderate new package plus focused artifact helper additions and tests.
- Files and areas to inspect: cleanup record serialization, selector matching, retention normalization, safety path handling, and package exports.
- Scope-control checks: no authority writes, no deletion calls, no CLI registration, no event projection, and no remote SDK imports.

## Implementation Steps

1. Add cleanup package scaffolding, errors, and public exports.
2. Implement cleanup records and strict plain-data serialization.
3. Implement retention helpers in `loom.artifacts` with tests over metadata-compatible payloads.
4. Implement bounded selector matching/explanations.
5. Implement local safety decisions over trusted roots and target records.
6. Add package, unit, and contract coverage.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_cleanup_api.py` or equivalent package import checks
- Required assertions or deferral reason: cleanup package imports are intentional and import-light.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/cleanup/`, `tests/unit/loom/test_artifacts.py`
- Required assertions or deferral reason: records, selectors, safety decisions, and retention helpers behave deterministically.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cleanup_records_contract.py` and artifact retention contract additions
- Required assertions or deferral reason: public cleanup records and retention helpers round-trip through stable plain-data payloads.

### Integration Suite

- Status: deferred
- Expected paths: none in Phase 1
- Required assertions or deferral reason: store collaboration and deletion are Phase 2/3 concerns.

### E2E Suite

- Status: deferred
- Expected paths: none in Phase 1
- Required assertions or deferral reason: CLI is Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: remote/provider cleanup is explicitly unsupported in Stage 21.

## Risks

- Path checks can accidentally approve symlink traversal if they resolve too early.
- Record names could overfit local filesystem deletion instead of future adapters.
- Retention helpers could be mistaken for enforcement policy if names imply automatic cleanup.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_cleanup_api.py
uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/test_artifacts.py
uv run pytest tests/contracts/test_cleanup_records_contract.py tests/contracts/test_external_artifact_records_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: records/errors/exports, retention helpers, selectors, safety helpers, then tests.
- Tests to run with each slice: run the targeted unit/contract path for the slice before broader validation.
- Decisions the executor must not revisit: no deletion, no authority persistence, no events, no CLI, no arbitrary query language, no automatic retention enforcement.
- Conditions that require stopping for the manager: selector matching requires expression parsing, safety approval requires authority facts unavailable in Phase 1, or retention requires provider-specific semantics.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally
- Final phase execution plan: completed locally
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
