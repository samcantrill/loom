# Phase 4 Execution Plan: Offline Import, Mutation Safety, And Deferred Repair Contracts

## Metadata

- Status: implemented
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 4: Offline Import, Mutation Safety, And Deferred Repair Contracts`
- Branch: `codex/offline-import-safety-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/offline-import-safety-hardening`
- Phase execution plan path: `docs/phases/offline-import-safety-hardening.md`
- Full plan: `docs/implementation-plans/implementation-plan-v11.md`
- Source phase: Phase 4, `v10-post` Offline Import, Mutation Safety, And Deferred Repair Contracts
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 3 merge; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase tightens persistence, historical import, and terminal mutation contracts
- Successor dependency notes: main v11 queue phases must not branch until this phase merges and the transition checkpoint is recorded
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 3 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: completed locally on 2026-05-13 after source inspection of offline import validation, import provenance, and terminal stage mutation paths
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Lock strict historical offline-import semantics and same-attempt success fencing before queue recovery and later reliability work depend on authority truth.

## Full-Plan Context

This is the final `v10-post` prerequisite phase. It must not add queue behavior or repair workflows. Its job is to make imported offline evidence authoritative historical truth, while keeping imported attempts distinct from live resumable work and requiring the live success path to go through fenced output commits.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 3 merged into `develop`
- Why this base branch is correct: Phase 3 merge metadata is on `develop` and there is no unmerged predecessor
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: lock offline import and terminal mutation semantics so later queue and recovery features build on strict historical truth instead of soft repair behavior.
- Required scope: keep offline-first explicit; require complete manifests and terminal run state; keep collision handling strict; preserve imported provenance; keep successful stage completion atomic and fence-guarded; keep imported offline attempts historical rather than resumable live work.
- Acceptance criteria: incomplete, non-terminal, or colliding offline imports fail explicitly; imported runs preserve offline provenance while becoming authoritative historical truth; terminal success cannot be recorded without the same-attempt fenced output commit.
- Explicit checkpoint: completion of this phase triggers the `v10-post -> v11` transition checkpoint before any main queue phase begins.

## Current Source And Harness Findings

- `validate_offline_import_manifest(...)` already rejects authored authoritative sources, incomplete manifests, non-terminal run status, non-terminal stage status, plan/stage mismatches, artifact/output mismatches, invalid event history, and evidence diagnostics with errors.
- `import_offline_evidence_manifest(...)` and `AuthorityRepository.import_offline_evidence_manifest(...)` already perform strict reject-by-default collision handling when an authority run identity exists.
- Imported runs store `metadata["authority_import"]`, replay offline events as `offline_import.replay.*`, and insert imported stage attempts with owner `offline-import`.
- `record_output_commit(...)` already performs a same-attempt, owner, lease, fencing-token, service-generation, and revision guarded atomic success update.
- `finish_stage_attempt(...)` is intended for terminal non-output states, but it currently accepts `StageStatus.SUCCEEDED`; that allows a successful live terminal stage mutation without an output commit.

## In-Scope Work

- Make the live `finish_stage_attempt(...)` path reject `StageStatus.SUCCEEDED` so success is recorded only through `record_output_commit(...)`.
- Keep failed, blocked, skipped, stale, and cancelled attempt finalization available through the existing fenced terminal path.
- Mark authority import provenance as historical-only and not resumable live work while preserving existing manifest and source provenance fields.
- Add focused unit and integration tests for strict import provenance, collision/incomplete/non-terminal import rejection, and success mutation safety.
- Update contract expectations only where offline-import result or client payload shape changes.

## Out-of-Scope Work

- Queue package, queue read models, scheduler policy, queue recovery, or worker dispatch.
- Merge, overwrite, fork, or repair import policies.
- Normal-path repair, inspection-based resume, or partial-attempt resume.
- Changing existing offline evidence collection semantics beyond import-admission validation.

## Assumptions

- Outputless successful live stages should still use `record_output_commit(...)` with an empty output mapping if they must be recorded as succeeded, because that is the only same-attempt fenced success mutation.
- Imported offline attempts are historical records only. Their owner and provenance may be read for diagnostics, but no live lease or resumable-attempt state is created during import.
- Strict collision rejection remains the only v11 policy for an already authoritative run identity.

## Scope Contract

Offline import converts complete terminal offline evidence into authority-owned historical truth. It must not create live leases, submitted operations, resumable attempts, or repair metadata. Live terminal success must remain tied to the same attempt that owns the active stage lease and fencing token, with the success update and output commit written atomically.

## Design Impact

- Maintainability: keeps safety rules in the authority repository where all service routes converge.
- Extensibility: future repair/import policies can be added explicitly without weakening the default strict import path.
- Domain neutrality: provenance records generic historical import policy rather than queue-specific behavior.
- Source-tree boundaries: changes stay in authority import, authority mutation safety, and related tests.

## Future Compatibility

The historical-only provenance fields give later queue/recovery code a stable way to avoid treating imported attempts as live resumable work. The success-fencing rule leaves room for future explicit outputless-success helpers only if they preserve same-attempt fencing and atomicity.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Allow `finish_stage_attempt(..., SUCCEEDED)` for outputless work | It creates a second success path that bypasses output commit atomicity and weakens queue recovery assumptions. |
| Treat imported offline attempts as resumable live attempts | Imports lack live leases and active worker ownership, so resume would be ambiguous and unsafe. |
| Add soft collision repair during import | The implementation plan explicitly reserves merge/overwrite/fork policies for future workflows. |
| Encode historical-only semantics only in docs | Later code needs a machine-readable provenance bit to distinguish historical import from live authority state. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Strict import still rejects otherwise useful partial historical cases | v11 queue work needs an unambiguous truth boundary before repair policy exists | A later roadmap adds an explicit repair/import workflow with separate validation and UX |
| Outputless success still goes through the output-commit API with an empty mapping | It preserves one fenced success path without adding another public mutation contract | A later public protocol explicitly models outputless success with equivalent fencing and atomicity |

## Reviewability

- Expected PR size and shape: small authority safety patch plus targeted tests.
- Files and areas to inspect: `src/loom/authority/_repository.py`, `tests/unit/loom/authority/test_repository_stage_lifecycle.py`, `tests/unit/loom/authority/test_offline_import.py`, and `tests/integration/authority/test_offline_import_api.py`.
- Scope-control checks: no queue package, no repair workflow, no relaxed import policy, no future-phase dispatch behavior.

## Implementation Steps

1. Add historical-only and resumable-live provenance fields to authority offline imports.
2. Reject successful terminal attempts through `finish_stage_attempt(...)` and keep non-success terminal statuses unchanged.
3. Add unit tests for repository success rejection and preserved fenced `record_output_commit(...)` success behavior.
4. Add unit and integration tests asserting imported provenance is historical-only, not resumable live work, and strict import rejection remains explicit.
5. Run targeted suites, then full PR validation and summary.

## Test Plan

### Package Suite

- Status: deferred
- Expected paths: not required
- Required assertions or deferral reason: no public package export or API surface is added.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_offline_import.py`, `tests/unit/loom/authority/test_repository_stage_lifecycle.py`
- Required assertions or deferral reason: offline import provenance records historical-only/non-resumable semantics; successful terminal attempt finalization through `finish_stage_attempt(...)` is rejected while fenced output commit success still works.

### Contract Suite

- Status: targeted
- Expected paths: `tests/contracts/test_offline_import_contract.py`
- Required assertions or deferral reason: offline import result/client payload contracts remain stable unless provenance shape changes are surfaced.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_offline_import_api.py`, `tests/integration/authority/test_mutation_api.py`, `tests/integration/authority/test_repository_stage_lifecycle.py`
- Required assertions or deferral reason: API import exposes historical-only provenance and live mutation routes reject success through the terminal-attempt path while keeping output commits fenced.

### E2E Suite

- Status: deferred
- Expected paths: not required
- Required assertions or deferral reason: no CLI or end-to-end queue behavior changes are in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM, network scheduler, or site-specific dependencies are introduced.

## Risks

- Tightening `finish_stage_attempt(...)` could reveal callers that treated it as an outputless success path; current source inspection found no public client method and no runner call sites.
- Provenance additions must be backward-compatible plain data because existing tests and read models only require current keys.
- Error categorization should remain stable enough for clients to treat the rejected success mutation as a conflict, not an internal error.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/authority/test_offline_import.py tests/unit/loom/authority/test_repository_stage_lifecycle.py tests/contracts/test_offline_import_contract.py tests/integration/authority/test_offline_import_api.py tests/integration/authority/test_mutation_api.py tests/integration/authority/test_repository_stage_lifecycle.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: provenance metadata first, success-path repository guard second, route-level regression coverage third.
- Tests to run with each slice: offline import tests after provenance changes; repository lifecycle tests after mutation guard; mutation API tests after service route coverage.
- Decisions the executor must not revisit: no queue behavior, no import merge/repair policy, no alternate success mutation path without output-commit fencing.
- Conditions that require stopping for the manager: any required public protocol redesign for outputless success or any evidence that existing in-scope runtime success paths cannot use `record_output_commit(...)`.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted and full validation passed
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: added explicit historical-only/non-resumable import
  provenance for offline evidence imports; kept imported attempts as
  `offline-import` historical records without active leases; rejected
  `finish_stage_attempt(..., SUCCEEDED)` so live success remains tied to
  same-attempt fenced `record_output_commit(...)`; added unit and integration
  regression coverage for import provenance and terminal mutation safety.
- Implementation validation: focused Phase 4 pytest command passed with 28
  tests; targeted Ruff on touched files passed; `make validate-pr` passed after
  Ruff, Pyright, default harness, config-extra harness, and build; `make
  test-summary` passed with 1832 passed, 12 skipped, and 1413 deselected.
- Refinement summary: no implementation refinement pass was needed after
  validation.
- Blocker-resolution summary: none.
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: none.
