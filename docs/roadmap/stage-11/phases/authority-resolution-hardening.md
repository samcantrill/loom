# Phase 1 Execution Plan: Authority Resolution And Supervisor Hardening

## Metadata

- Status: implemented
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 1: Authority Resolution And Supervisor Hardening`
- Branch: `codex/authority-resolution-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-resolution-hardening`
- Phase execution plan path: `docs/roadmap/stage-11/phases/authority-resolution-hardening.md`
- Full plan: `docs/roadmap/stage-11/implementation-plan.md`
- Source phase: Phase 1, `v10-post` Authority Resolution And Supervisor Hardening
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase hardens authority/supervisor contracts
- Successor dependency notes: Phase 2 branches from `develop` if this phase merges, otherwise from this branch
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: not needed; scope remained within the recorded phase contract
- Setup limitations: GitHub operations require approved network access; `uv`
  validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Harden the authority resolver and local supervisor startup contract so later
queue phases can rely on live authority readiness, explicit workspace-default
state directories, and one live authority per workspace.

## Full-Plan Context

This is the first `v10-post` prerequisite phase. It must not introduce queue
code. Later queue phases rely on these authority entrypoints as live mutation
truth rather than treating registry records as authority state.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none
- Why this base branch is correct: all earlier v10 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: finalize strict authority resolution, registry semantics, and explicit workspace-default supervisor behavior.
- Required scope: live readiness, registry-as-hint behavior, one-authority-per-workspace, workspace-default state-dir option, and stale generation invalidation.
- Required checkpoints: supervisor CLI/helpers expose `--use-workspace-default`; second live authority start is rejected.
- Acceptance criteria: mutating paths reject stale/missing live authority facts, supervisor commands expose explicit workspace default, and restart generation changes remain observable.

## Current Source And Harness Findings

- Existing resolver and registry modules already expose typed stale, wrong-workspace, incompatible-generation, unavailable, and unhealthy outcomes.
- Supervisor helpers already rotate service generations on restart and write registry records.
- Missing gap: no explicit workspace-default state-dir option and no guard against starting another live authority for the same workspace through a different state directory.
- Full-gate finding: the default suite also exposed an existing invalid
  offline-manifest CLI classification gap and a replay-event assertion bug; both
  were repaired as validation blockers without changing queue scope.

## In-Scope Work

- Add a reusable explicit workspace-default supervisor state-dir resolver.
- Add `--use-workspace-default` to authority supervisor lifecycle CLI commands.
- Reject a second live authority supervisor for the same workspace when the current registry points to a live ready service.
- Add focused unit, integration, and CLI smoke coverage.
- Repair validation blockers that prevent the full PR gate from proving the
  phase.

## Out-of-Scope Work

- Queue service, queue models, dispatch, or resource pools.
- Multi-authority workspace support.
- Hidden implicit workspace defaults for `start`.
- Runtime worker and SLURM live-path tightening owned by Phase 2.

## Assumptions

- Registry records remain bootstrap hints; the second-authority guard checks live process/readiness before rejecting.
- Existing generation checks in readiness and mutation metadata remain the stale-client invalidation mechanism for this phase.

## Scope Contract

Supervisor state-dir selection remains explicit: callers pass either
`--state-dir` or `--use-workspace-default`, and using both is invalid. The
workspace default resolves to `<workspace-root>/.loom/authority/service`.
Starting a different state directory for a workspace with a live ready authority
fails with `authority_supervisor.workspace_authority_exists`.

## Design Impact

- Maintainability: centralizes workspace-default path resolution in supervisor helpers.
- Extensibility: preserves the one-authority-per-workspace assumption without adding multi-authority abstractions.
- Domain neutrality: no domain-specific queue or scheduler behavior is introduced.
- Source-tree boundaries: changes stay in authority, CLI, and tests.

## Future Compatibility

The explicit workspace-default path can be reused by later supervisor
co-management without making implicit startup behavior part of the contract.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implicitly default `start` to `.loom/authority/service` | The plan requires an explicit workspace-default surface. |
| Reject based on registry record alone | Registry records are hints, so the guard checks live process/readiness first. |
| Allow multiple live authorities per workspace | The current v10-post contract preserves one authority per workspace. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Workspace-default state is still local-supervisor-specific | Phase 1 only hardens current supervisor behavior | Future multi-authority or hosted service work needs different state routing |

## Reviewability

- Expected PR size and shape: small authority/supervisor and CLI patch plus focused tests.
- Files and areas to inspect: `src/loom/authority/supervisor.py`, `src/loom/cli/authority.py`, supervisor tests, and the small offline-evidence validation blocker repair.
- Scope-control checks: no queue package or runtime worker changes.

## Implementation Steps

1. Add explicit workspace-default state-dir resolution.
2. Wire the option through supervisor lifecycle helpers and CLI commands.
3. Guard startup against a second live ready authority for the same workspace.
4. Add focused tests for path resolution, conflicts, lifecycle behavior, and CLI smoke.

## Test Plan

### Package Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no package export surface changed outside `loom.authority.supervisor`.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_supervisor.py`, `tests/unit/loom/pipeline/stores/test_authority_factory.py`
- Required assertions or deferral reason: state-dir selection, duplicate-live-authority guard, and existing strict factory behavior.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_resolution_contract.py`
- Required assertions or deferral reason: resolver failure categories remain stable.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_supervisor_lifecycle.py`
- Required assertions or deferral reason: real supervisor lifecycle supports explicit workspace default; offline import API replay assertions keep the default suite passing.

### E2E Suite

- Status: targeted
- Expected paths: `tests/e2e/test_authority_supervisor_cli.py`
- Required assertions or deferral reason: CLI smoke now uses the explicit workspace-default option.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM or site-specific behavior in scope.

## Risks

- Supervisor tests start local processes; final validation must confirm cleanup remains reliable.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/authority/test_supervisor.py tests/integration/authority/test_supervisor_lifecycle.py tests/contracts/test_authority_resolution_contract.py tests/unit/loom/pipeline/stores/test_authority_factory.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: supervisor state-dir option, CLI wiring, duplicate authority guard, tests.
- Tests to run with each slice: focused supervisor/resolver suites listed above.
- Decisions the executor must not revisit: no implicit supervisor default and no queue code.
- Conditions that require stopping for the manager: any need to redesign authority registry truth or multi-authority behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed
- PR review: unused
- Blocker resolution: 1/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: added explicit workspace-default supervisor state-dir resolution, CLI wiring, live duplicate-authority guard, and small validation-blocker repairs for invalid offline-manifest CLI classification and replay-event assertions.
- Implementation validation: focused supervisor/resolver pytest command passed with 36 tests; validation-blocker pytest command passed with 25 tests; `make validate-pr` passed; `make test-summary` passed with 1821 passed, 12 skipped, 1402 deselected.
- Refinement summary: not needed.
- Blocker-resolution summary: 1/3 used for full-gate validation blockers in CLI/offline-evidence tests.
- PR preparation: PR body prepared and PR opened at
  https://github.com/samcantrill/loom/pull/137 targeting `develop`.
- Stack maintenance: none yet.
- Remaining blockers: none.
