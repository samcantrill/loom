# Phase 8 Execution Plan: HPC Authority Deployment

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 8 - HPC Deployment Modes And Fallback Capabilities
- Status: in_progress
- Branch: `codex/hpc-authority-deployment`
- Worktree: `/home/samcantrill/work/loom-worktrees/hpc-authority-deployment`
- Stack predecessor: none; Phase 7 merged before branch creation.
- Base branch: `develop`
- PR target branch: `develop`
- PR: pending
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 8: HPC Authority Deployment`
- Draft pass: complete on 2026-05-10
- Refine pass: complete on 2026-05-10 because this phase defines deployment
  profile contracts, fallback semantics, and deferred reconciliation behavior.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## Scope

This phase makes authority deployment modes explicit before later phases route
runtime and SLURM call sites through them.

The implementation will:

- Add profile diagnostics for co-located, managed-service,
  allocation-scoped-service, direct-database, and deferred-finalization
  authority deployments.
- Add deterministic preflight records that report missing endpoints,
  service-health failures, compute-to-authority reachability assumptions,
  single-host capability downgrades, and live-worker/deferred-mode mismatch.
- Keep profile checks backend-neutral and cheap to import.
- Add deferred result envelope records that are plain-data stable and do not
  carry live authority credentials or fencing material.
- Add guarded deferred reconciliation helpers that accept envelopes only
  through a `PerRunAuthorityStore`, reject stale/cancelled/superseded/malformed
  evidence, and require reconciler-held fencing material for output commits.
- Add focused unit, contract, and integration coverage for profile selection,
  service-unreachable preflight, co-located downgrades, envelope validation,
  stale rejection, and authority-mediated reconciliation.
- Document SLURM handoff expectations for live authority and deferred
  finalization without changing all SLURM runtime call sites in this phase.

## Out Of Scope

- System-wide service backend adoption in runner, CLI, worker, and SLURM paths.
- Hosted production operations, authentication, authorization, tenancy, or high
  availability.
- A scheduler-managed service process implementation.
- Treating deferred envelopes or shared files as lifecycle authority.
- Making deferred finalization equivalent to live worker authority.
- Removing transitional SQLite authority.

## Design Impact

Very high. This phase defines the compatibility boundary between live
authority, single-host development authority, and offline deferred
finalization.

## Future Compatibility

Phase 9 can route concrete runtime and SLURM call sites through these profile
and envelope contracts without inventing deployment semantics at each call
site.

## Alternatives Rejected

- Assuming a long-running login-node daemon is always available. Many HPC sites
  kill or forbid that topology.
- Letting workers mark success locally when they cannot reach authority.
- Passing live fencing material inside deferred worker envelopes.

## Debt Introduced

- The preflight checks are deterministic contracts and do not probe real
  networks or schedulers yet.
- Reconciliation uses the existing public authority operations; a future
  durable service backend can collapse validation and commit into a
  backend-native transaction.

## Acceptance Criteria

- Deployment diagnostics distinguish live worker authority, deferred
  finalization, and single-host co-located authority.
- Live submitted-worker admission fails closed when endpoint, service health,
  or compute reachability is missing or unproven.
- Deferred finalization workers cannot carry live fencing material in their
  result envelopes.
- Deferred envelopes round-trip as plain data and reject malformed, stale,
  cancelled, superseded, or inconsistent evidence.
- Successful deferred reconciliation commits output facts only through an
  authority store and reconciler-held fencing token.
- Failed deferred reconciliation transitions stages through the authority
  store, not local lifecycle files.
- SLURM-facing docs/tests show the handoff fields for live authority and
  deferred finalization.

## Suite Obligations

- Package: profile and envelope imports remain lightweight and avoid concrete
  service, multiprocessing, or scheduler imports.
- Unit: profile diagnostics, preflight failures, envelope validation, stale
  rejection, and capability downgrade behavior.
- Contract: deferred reconciliation contract over an authority store.
- Integration: local simulations for managed service health/unreachable
  preflight and offline envelope reconciliation.
- E2E: not required until Phase 9 call-site adoption.
- Opt-in: real HPC topology tests only.

## Implementation Summary

- Added backend-neutral deployment profile summaries and preflight diagnostics
  for co-located, managed-service, allocation-scoped-service, direct-database,
  and deferred-finalization authority profiles.
- Added deterministic live-worker checks for endpoint presence, service health,
  compute-to-authority reachability, capability admission, and profile
  mismatch.
- Added deferred result envelopes that round-trip as plain data and reject live
  fencing material in worker-produced payloads.
- Added guarded deferred reconciliation through `PerRunAuthorityStore`, with
  stale, cancelled, superseded, terminal-submission, missing-fence, and
  authority-rejected outcomes.
- Documented SLURM authority handoff profiles and separated live authority
  worker fields from deferred result envelopes.
- Added package, unit, contract, and integration coverage for profile
  diagnostics, service-unreachable preflight, local service downgrade
  diagnostics, envelope validation, and authority-mediated reconciliation.

## Validation Evidence

- Targeted Phase 8 suite:
  `uv run --extra config pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/stores/test_deferred_finalization.py tests/contracts/test_deferred_finalization_contract.py tests/integration/pipeline/test_authority_deployment_profiles.py -q`
  passed with 47 tests.
- `uv run --extra config pyright` passed with 0 errors, 0 warnings, and 0
  informations.
- `make validate-pr` passed Ruff, Pyright, default tests, config-extra tests,
  and build.
- `make test-summary` passed:

  | Suite | Result |
  | --- | --- |
  | package | 57 passed, 1 skipped |
  | unit | 852 passed, 1 skipped |
  | contract | 112 passed, 2 skipped |
  | integration | 98 passed, 8 skipped, 10 deselected |
  | e2e | 39 passed, 1 deselected |
  | config-extra | 420 passed, 1161 deselected |

## Stop Conditions

- The phase requires changing every SLURM or worker call site to express the
  profile boundary.
- Deferred result envelopes require live authority credentials or fencing
  material in the worker-produced payload.
- Reconciliation cannot reject stale or cancelled evidence before making a
  lifecycle mutation.
