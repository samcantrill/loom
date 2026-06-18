# Phase 8 Execution Plan: Workspace/Sweep Coordination Foundation

## Metadata

- Status: final phase execution plan; ready for implementation.
- Feature focus: Persistence And Concurrency Foundation
- PR title:
  `Persistence And Concurrency Foundation - Phase 8: Workspace/Sweep Coordination Foundation`
- Branch: `codex/workspace-coordination`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/workspace-coordination`
- Phase execution plan path: `docs/roadmap/stage-9/phases/workspace-coordination.md`
- Full plan: `docs/roadmap/stage-9/implementation-plan.md`
- Source phase: Phase 8 - Workspace/Sweep Coordination Foundation
- Stack predecessor: none; Phases 1, 2, 3, 4, 5, 6, and 7 are merged into
  `develop`.
- Base branch: `develop`
- Base commit: `ee863fd032444e9173713017e38b81505984c0c3`
  (`docs: record v9 phase 7 merge`)
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after the implementation
  stays in Phase 8 scope, required validation passes or unavailable checks are
  justified, automated review has no blocking findings, CI passes, and the PR
  still targets `develop`.
- Workflow path: expanded path because this phase implements public-ish
  cross-run coordination contracts, SQLite transaction behavior, lease and
  counter semantics, and future sweep/service backend compatibility.
- Successor dependency notes: v11 deterministic sweeps may use this
  coordination foundation for concurrent trial claiming and resource limits,
  but simple sequential manifests remain document-shaped and out of the
  coordination store by default.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no
  blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement and
  confirmation review were not needed.
- Draft pass: complete by `loom_phase_planner` in draft-plan commit
  `f49de63`.
- Refine pass: complete on 2026-05-10 by `loom_phase_planner`; the expanded
  pass reread the draft plan, implementation-plan v9, `AGENTS.md`,
  `docs/structure.md`, `.codex` phase prompts/template, current coordination
  contracts, capability records, SQLite authority boundaries, in-memory
  conformance support, coordination contract tests, and sweep/run-store docs,
  then tightened minimal protocol-extension scope, counter recovery limits,
  local SQLite safety diagnostics, suite obligations, and stop conditions.
- Setup limitations: GitHub auth and `origin/develop` were verified with
  approved network access; branch/worktree creation required approved sandbox
  escalation after the default sandbox could not write namespaced git refs.
- Blockers: none.

## Objective

Implement the local workspace/sweep coordination foundation behind the Phase 1
`WorkspaceCoordinationStore` contract so future concurrent sweeps can claim
trials, reserve named resources, guard global counters, and recover abandoned
cross-run leases without copying per-run stage lifecycle state or replacing
derived run catalog behavior.

## Full-Plan Context

Phases 1-7 established per-run authority contracts, the run-local SQLite
backend, read models, the public serial hard swap, backend diagnostics, and
opt-in bounded local parallel stage execution. Phase 8 completes the v9 hybrid
authority boundary by adding the cross-run side. It must stay a foundation:
full sweep execution, adaptive algorithms, scheduler queues, fairness policy,
distributed controllers, service backends, remote authority, and dynamic trial
generation remain future work.

## Stack Context

- Root or stacked phase: root phase based directly on `develop`.
- Current predecessor branch or PR: none; Phase 7 is merged.
- Why this base branch is correct: implementation-plan v9 records Phases 1-7
  as `merged`, and the manager assigned current `origin/develop` after the
  Phase 7 merge as the stack base.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is
  needed. If `develop` advances before PR preparation, rebase this root branch
  onto updated `develop` and keep the PR target as `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no
  successor branch depends on it.

## Source Phase Summary

- Goal: establish compact cross-run coordination for future multi-run
  concurrency and large sweeps without implementing full sweep execution.
- Required scope: local SQLite or selected local backend implementation for
  workspace/sweep identity, trial references, trial leases, resource leases,
  global counters, ordinary `run_uri` references, capability declarations, and
  recovery scans.
- Required checkpoints: cross-run records only, per-run lifecycle remains in
  each run's authority backend, SQLite coordination declares local or
  same-host safety only, and docs keep v11/later behavior deferred.
- Acceptance criteria: trial/resource leases are claimable, renewable,
  releasable, expirable, and recoverable; counters are backend guarded and
  recover from abandoned leases where possible; catalog and sweep/dashboard
  summaries stay derived; sequential deterministic sweeps remain manifest
  compatible.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/coordination.py` already defines
  `WorkspaceCoordinationStore`, `WorkspaceIdentity`, `SweepIdentity`,
  `TrialReference`, `TrialLeaseRecord`, `ResourceLeaseRecord`,
  `ConcurrencyCounter`, and `CoordinationRecoveryRecord`.
- The current coordination protocol has create/list/acquire/release/counter
  read/increment/recovery operations, but Phase 8 acceptance requires explicit
  renew and failure semantics for leases and guarded counter behavior. Minimal
  protocol tightening is in scope when needed to satisfy those acceptance
  criteria.
- `tests/support/authority_stores.py` provides
  `InMemoryWorkspaceCoordinationStore` for existing conformance tests. It is
  useful as a fake but should not become the production backend.
- `tests/contracts/test_workspace_coordination_contract.py` proves the
  current in-memory contract records cross-run facts only. Phase 8 should
  broaden these contract tests to run against both fake and SQLite/local
  coordination implementations.
- No concrete SQLite workspace coordination module exists yet. The new
  implementation should follow the private-schema pattern from
  `sqlite_authority.py` without exposing SQL layout as a public contract.
- `src/loom/pipeline/stores/sqlite_authority.py` is intentionally per-run and
  declares `CROSS_RUN_COORDINATION` and `GLOBAL_COUNTERS` unsupported. Phase 8
  should add a separate coordination backend instead of extending the per-run
  database into workspace authority.
- `src/loom/pipeline/stores/capabilities.py` already contains
  `CROSS_RUN_COORDINATION`, `GLOBAL_COUNTERS`, backend lease time, recovery,
  consistent-read, and unsafe remote/shared-filesystem diagnostic vocabulary.
  Reuse it for coordination capability and loud multi-host diagnostics.
- `docs/structure.md`, `docs/features/run-store.md`, and
  `docs/features/sweeps.md` already describe the strict boundary:
  workspace/sweep coordination owns identity, trial references, resource
  leases, counters, `run_uri` pointers, and recovery scans, but not per-stage
  run state or run catalog truth.

## In-Scope Work

- Implement a local SQLite workspace/sweep coordination store under the
  pipeline store boundary using only the standard-library `sqlite3` module.
- Keep the coordination database placement and schema private. The database
  may be workspace-local or explicitly constructed by path, but the public
  contract is the `WorkspaceCoordinationStore` behavior, not table names.
- Persist workspace and sweep identity records with metadata, schema checks,
  revisions, and deterministic duplicate/unknown-parent failures.
- Persist trial references with ordinary `run_uri` pointers and trial state.
  Trial records must not copy run status, stage status, attempts, commits,
  artifact facts, submitted operations, or per-run snapshots.
- Implement trial lease acquisition, renewal, release, failure, expiry, and
  recovery scanning with owner ids, fencing tokens, backend-owned local UTC
  time, revision evidence, and deterministic errors for stale tokens.
- Implement named resource leases with positive amounts, owner/fencing checks,
  lease renewal/release/failure, expiry, and recovery scanning.
- Implement guarded global counter records for workspace-level concurrency
  accounting, including optional limits where needed to make counter updates
  atomic and loud failures when a requested increment would exceed a limit.
- Ensure abandoned or expired leases can be surfaced as recovery records and
  can make reserved resource/counter capacity available again where the
  backend can prove the lease is expired.
- Add capability declarations for the local coordination backend that support
  cross-run coordination, global counters, backend lease time, revisioned
  reads, consistent reads, and recovery scans while explicitly limiting safety
  to local or same-host coordination.
- Add loud diagnostics or unsupported-capability records for remote,
  multi-host, or shared-filesystem assumptions the local SQLite coordination
  backend cannot prove.
- Update docs that explain how v11 deterministic sweeps and future service or
  scheduler backends can build on this boundary, and that simple sequential
  sweep manifests remain compatible without database-first coordination.
- Add only diagnostic CLI/API surface if implementation needs a public smoke
  path. Any CLI added in this phase must be read-only or capability-focused,
  not a sweep runner or mutation command.

## Out-of-Scope Work

- No full sweep runner, `loom sweep run`, adaptive sweep algorithm, trial
  planning language, deterministic sweep expansion, or result collection.
- No distributed controller, scheduler-backed queue, fairness policy, worker
  pool, service backend, Postgres backend, remote authority, hosted tracker, or
  cloud SDK dependency.
- No per-stage lifecycle, attempt, lease, submitted-operation, commit, artifact
  fact, event, or snapshot duplication in coordination tables.
- No replacement for `RunCatalog`, status summaries, backend diagnostics, or
  future sweep/dashboard projections.
- No migration path for old run directories, public SQL/schema contract,
  repair/mutation CLI, export/import, bundle, or snapshot command.
- No changes to the serial default path or Phase 7 bounded local parallel
  stage execution except capability records shared by store diagnostics.
- No dynamic DAG mutation, runtime trial generation, retry policy, timeout
  policy, cancellation policy redesign, or resource scheduling fairness.

## Assumptions

- The assigned stack metadata is authoritative: base branch `develop`, PR
  target `develop`, stack predecessor `none`.
- The selected local backend approach should be a separate SQLite coordination
  store beside `SQLitePerRunAuthorityStore`, not a combined per-run/workspace
  database.
- The executor may choose exact class/function names, but the store contract,
  capability vocabulary, and cross-run-only authority boundary are fixed.
- Backend-owned time for the local coordination store means the store's local
  UTC clock or an injectable deterministic test clock. It does not imply
  multi-host clock safety.
- Counter recovery should be as strong as the lease/counter association the
  implementation records. If a proposed counter shape cannot be recovered
  deterministically, the executor must keep the counter API narrower and record
  the limitation rather than inventing sweep policy.

## Scope Contract

`WorkspaceCoordinationStore` is the cross-run coordination authority. It may
own workspace/sweep identity, trial references, trial leases, resource leases,
global counters, `run_uri` pointers, capability records, schema checks,
revisions, and recovery records. It must not become a per-run state backend,
catalog sidecar, sweep runner, scheduler queue, or dashboard projection.

The local SQLite coordination backend is a first implementation behind that
contract. It should use short transactions and private schema constraints for
atomic claims, renewals, releases, counter updates, and recovery scans. SQLite
coordination is local or same-host only; explicit multi-host, remote, or
service-grade assumptions must produce loud diagnostics rather than optimistic
success.

Trial leases and resource leases use owner ids and fencing tokens. A lease may
be renewed, released, or failed only by the current owner with the current
token and while the backend considers the lease active. Expired leases are not
valid write authority and must appear in recovery scans until released,
failed, or otherwise reconciled by a future policy.

Global counters are coordination facts, not policy engines. They should support
atomic guarded updates and readable revision evidence, but they must not
choose sweep fairness, trial ordering, adaptive search, or scheduler admission
policy.

## Design Impact

- Maintainability: a separate coordination backend preserves the v9 hybrid
  authority split and prevents sweep/resource facts from leaking into per-run
  lifecycle code.
- Extensibility: future service, scheduler, or remote coordination backends can
  implement the same contract while declaring stronger lease-time and
  multi-host capabilities.
- Domain neutrality: records use generic workspace, sweep, trial, resource,
  counter, and `run_uri` vocabulary without metric, model, dataset, or
  project-code semantics.
- Source-tree boundaries: implementation stays under
  `loom.pipeline.stores`; execution and sweep modules do not own the backend;
  `loom.runs` remains a derived query facade; CLI remains presentation if any
  diagnostic surface is added.

## Future Compatibility

- V11 deterministic sweeps can plan ordinary runs in manifest form and opt
  into coordination only for concurrent trial claims, resource limits, and
  recovery.
- Future scheduler/service backends can replace the local coordination store
  by satisfying the same lease, counter, capability, and recovery semantics.
- Remote stores and dashboards can consume `run_uri` references and derived
  summaries without reading private coordination tables.
- Stronger multi-host semantics can be added by a backend that declares central
  time or service-owned lease safety; this phase must not pretend SQLite has
  those properties.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Store sweep/trial leases in each per-run authority database | Cross-run admission and resource claims would be fragmented and would couple sweep coordination to per-stage lifecycle truth. |
| Extend `RunCatalog` into the coordination authority | The catalog is a derived projection and cannot safely own claims, leases, counters, or recovery decisions. |
| Reuse private `SQLitePerRunAuthorityStore` tables for workspace facts | The per-run SQLite backend is run-local and intentionally reports cross-run coordination unsupported. Combining them would blur authority boundaries and schema privacy. |
| Defer all concrete coordination implementation to v11 | V11 would have to retrofit lease and counter semantics after sweep behavior depends on them, increasing compatibility risk. |
| Implement full sweep scheduling or fairness now | Phase 8 is a foundation phase; policy belongs with concrete sweep execution and scheduler plans. |
| Make coordination mandatory for simple sequential sweeps | Sequential deterministic sweeps can remain manifest-driven collections of ordinary runs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local SQLite coordination is only local or same-host safe | V9 avoids service/Postgres dependencies while proving the contract and transaction semantics. | Multi-host sweeps, remote controllers, shared-filesystem guarantees, or service-backed schedulers need stronger central time and locking. |
| Coordination contract may need additional v11 sweep fields | V9 implements the compact foundation before full sweep workflows exist. | V11 sweep planning/running requires a fact that cannot be represented as identity, trial reference, lease, resource, counter, run reference, or recovery record. |
| Counter recovery may be limited to capacity tied to active leases | This keeps Phase 8 out of fairness and scheduler policy. | Future sweeps need strict accounting across retries, cancellation, quotas, or external resource pools. |

## Reviewability

- Expected PR size and shape: moderate store/test/docs PR centered on
  coordination contracts, a local SQLite coordination backend, conformance
  coverage, integration concurrency tests, and documentation updates.
- Files and areas to inspect: `src/loom/pipeline/stores/coordination.py`,
  any new SQLite coordination module, `src/loom/pipeline/stores/__init__.py`,
  `src/loom/pipeline/stores/capabilities.py` only if diagnostics need
  tightening, `tests/support/authority_stores.py`, coordination contract/unit
  tests, SQLite integration tests, and run-store/sweep docs.
- Scope-control checks: no `loom.runs` authority writes, no per-run private
  SQL table access, no sweep runner, no scheduler queue, no stage lifecycle
  duplication, no non-stdlib runtime dependency, and no optimistic multi-host
  capability claims.

## Implementation Steps

1. Tighten the coordination contract only where Phase 8 acceptance requires
   it: lease renew/fail behavior, guarded counter semantics, serialization,
   capability records, and fake conformance support.
2. Add the local SQLite coordination backend with private schema,
   schema-version checks, workspace/sweep/trial persistence, lease operations,
   guarded counters, revision evidence, and recovery scans.
3. Extend shared contract tests so both the in-memory fake and SQLite/local
   coordination store prove cross-run-only facts, lease fencing, renew/release
   failures, counter guards, capability declarations, and schema policy.
4. Add deterministic integration coverage for concurrent trial claims,
   resource contention, counter limits, expired/abandoned lease recovery, and
   ordinary `run_uri` references without reading per-run state.
5. Update run-store, structure, and sweep docs to describe the implemented
   local coordination backend, local/same-host limitations, deferred v11
   behavior, and continued compatibility for sequential sweep manifests.
6. If a CLI or API smoke path is introduced, keep it diagnostic-only and add
   focused parser/output tests plus an e2e smoke; otherwise leave e2e
   explicitly deferred.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_import_boundaries.py`, and any package import tests
  affected by new exports.
- Required assertions: public coordination exports remain cheap and stable;
  concrete SQLite coordination implementation does not make package-root
  imports heavy; no import cycles between stores, execution, runs,
  diagnostics, and CLI.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_models.py`
  or a new `tests/unit/loom/pipeline/stores/test_workspace_coordination.py`,
  plus targeted capability/schema tests if those modules change.
- Required assertions: model validation and round trips; lease owner/fencing
  renewal, release, failure, and expiry decisions; counter validation and
  guarded update behavior; capability declarations and unsupported
  multi-host/remote diagnostics; schema failure mapping.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_workspace_coordination_contract.py`.
- Required assertions: fake and SQLite/local stores both satisfy
  `WorkspaceCoordinationStore`; stores persist only cross-run facts; trial and
  resource leases are claimable, renewable, releasable, expirable, and
  recoverable; guarded counters and recovery records have deterministic
  revision evidence; unsupported capabilities are machine-readable.

### Integration Suite

- Status: required.
- Expected paths: a new
  `tests/integration/pipeline/test_workspace_coordination.py` or equivalent.
- Required assertions: SQLite-backed concurrent synthetic trial claims cannot
  double-claim a trial; resource lease contention and counter limits are
  transactional; expired abandoned leases appear in recovery scans and release
  reclaimable capacity where supported; trial records reference ordinary
  `run_uri` values without opening per-run databases or reading run state.

### E2E Suite

- Status: deferred by default.
- Expected paths: none unless a diagnostic CLI surface is introduced.
- Required assertions or deferral reason: Phase 8 does not implement a user
  sweep runner or required CLI workflow. If implementation adds a minimal
  diagnostic command, add a focused e2e smoke that proves read-only
  presentation and no sweep execution.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: default tests must remain local,
  deterministic, synthetic, and filesystem-only. Timing-sensitive stress,
  multi-host, remote-service, scheduler, or external database tests are out of
  scope.

## Risks

- Public-contract drift: the existing protocol may need minimal additions for
  renew/fail/counter limits. Keep changes narrow and backed by contract tests.
- Split authority: accidentally copying per-run lifecycle facts into
  coordination tables would violate the v9 hybrid boundary.
- SQLite overclaim: local SQLite can prove useful single-host semantics but
  must not claim distributed lease safety.
- Counter semantics: counters can easily become scheduler policy. Keep them as
  guarded coordination facts and defer fairness/admission policy.
- Recovery ambiguity: expired leases should be detectable without silently
  marking trial work succeeded, failed, or retried.

## Stop Conditions

- Stop if implementation requires a non-stdlib runtime dependency, a service
  process, Postgres, remote storage, a hosted scheduler, or network services.
- Stop if satisfying the phase requires copying per-run stage lifecycle,
  attempt, submitted-operation, commit, artifact, event, or snapshot facts into
  workspace/sweep tables.
- Stop if the local SQLite backend would need to claim multi-host,
  shared-filesystem, or remote coordination safety beyond local or same-host
  guarantees.
- Stop if the counter design cannot recover abandoned lease capacity
  deterministically without implementing scheduler fairness or sweep admission
  policy.
- Stop if the executor finds that `WorkspaceCoordinationStore` needs a broad
  redesign rather than the minimal renew/fail/counter tightening identified in
  this plan.
- Stop if a proposed CLI surface becomes a sweep runner, mutation/repair
  command, export/snapshot workflow, or supported SQL inspection path instead
  of a diagnostic-only surface.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/stores/test_authority_models.py tests/contracts/test_workspace_coordination_contract.py
uv run pytest tests/integration/pipeline/test_workspace_coordination.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: protocol/model tightening first, SQLite/local
  backend second, contract and fake conformance third, integration concurrency
  proof fourth, docs last.
- Tests to run with each slice: package import tests after export changes,
  unit model/capability tests after contract changes, contract tests after fake
  and SQLite conformance, integration tests after SQLite transaction behavior,
  then final `make validate-pr` and `make test-summary` during PR preparation.
- Decisions the executor must not revisit: separate coordination authority
  from per-run authority; keep SQLite schema private; use stdlib `sqlite3`;
  declare local/same-host safety only; keep sequential sweep manifests
  compatible; do not implement sweep execution or scheduler fairness.
- Conditions that require stopping for the manager: implementation needs
  non-stdlib runtime dependencies, public SQL/schema guarantees, per-run state
  duplication, a full sweep runner, distributed multi-host safety claims, or a
  broad contract redesign beyond minimal Phase 8 acceptance gaps.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-10 by
  `loom_phase_refiner`; fixed a fake/SQLite conformance gap for duplicate
  workspace and sweep identity failures and added contract coverage.
- PR review: used on 2026-05-10 by the managing agent; review covered the
  Phase 8 SQLite coordination backend, protocol extensions, fake conformance,
  contract/integration coverage, docs, target branch, and validation evidence,
  and found no blocking findings.
- Blocker resolution: 3/3 used on 2026-05-10 by the managing agent; fixed a
  GitHub CI-only race in the existing parallel failure-policy integration test
  by first making the failing support stage wait until the independent branch
  had started before failing, then making the fixture submit that independent
  branch before the failing branch so GitHub runners could not exhaust the wait
  before the independent task started. The final pass raised the bounded
  parallel smoke test's explicit coordination timeout so isolated harness runs
  do not fail before both worker tasks have a fair scheduling window.

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in commit `f49de63`.
- Final phase execution plan: refined to final/scope-complete status in this
  pass; locks the separate cross-run coordination authority, local SQLite-only
  implementation boundary, minimal protocol tightening, counter recovery
  limits, suite obligations, and stop conditions.
- Implementation summary: complete. Added the cross-run coordination protocol
  extensions, local SQLite workspace coordination backend, in-memory
  conformance support, package/contract/unit/integration coverage, and docs
  for local or same-host coordination limits without adding sweep runner,
  scheduler, CLI mutation, distributed controller, or per-run lifecycle
  duplication.
- Implementation validation: focused Phase 8 package/import, unit, contract,
  and integration pytest validation passed on 2026-05-10: 55 passed. Final
  post-blocker `make validate-pr` passed after refinement: Ruff, Pyright,
  default harness (1088 passed, 18 skipped, 14 deselected), config-extra
  harness (420 passed, 1117 deselected), and `uv build`. Final post-blocker
  `make test-summary` passed and generated `build/test-summary.md` at
  `2026-05-10T00:41:39+00:00` with 1534 passed, 0 failed, 0 errors, 12
  skipped, and 1128 deselected. The sandboxed focused command could not write
  the shared uv cache, so it was rerun with approved access.
- Refinement summary: expanded-path implementation refinement completed. The
  in-memory workspace coordination conformance store now rejects duplicate
  workspace and sweep identities like the SQLite backend, and contract tests
  cover duplicate identity and unknown-parent failures across both backends.
- Blocker-resolution summary: passes 1/3, 2/3, and 3/3 fixed
  `tests/integration/pipeline/test_parallel_execution.py` stability by making
  the failure-policy fixture deterministic about already-running independent
  work and making the bounded parallel smoke test tolerate slower isolated
  harness scheduling.
- PR preparation: PR #108 opened against `develop`:
  https://github.com/samcantrill/loom/pull/108.
- Stack maintenance: no predecessor; rebase onto updated `develop` if needed
  before PR preparation.
- Remaining blockers: none.
