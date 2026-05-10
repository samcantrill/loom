## Summary

This PR implements Phase 8 by defining explicit authority deployment profiles
and deferred-finalization contracts before system-wide service backend adoption.

The change keeps live authority, co-located development authority, and deferred
result envelopes separate. Deferred workers produce evidence only; lifecycle
state changes still go through authority-backed reconciliation.

## Changes

- Added deployment profile summaries and preflight diagnostics for co-located,
  managed-service, allocation-scoped-service, direct-database, and
  deferred-finalization authority profiles.
- Added live-worker preflight checks for endpoint presence, service health,
  compute-to-authority reachability, capability admission, and selected-profile
  mismatch.
- Added plain-data deferred result envelopes that reject worker-carried live
  fencing material.
- Added deferred reconciliation helpers that accept envelopes only through
  `PerRunAuthorityStore`, reject stale/cancelled/superseded evidence, and
  require reconciler-held fencing material for output commits.
- Documented SLURM authority handoff profiles and separated live authority
  handoff fields from deferred result envelopes.
- Added package, unit, contract, and integration coverage for profile
  diagnostics and deferred reconciliation.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build |
| package | 57 passed, 1 skipped |
| unit | 852 passed, 1 skipped |
| contract | 112 passed, 2 skipped |
| integration | 98 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1161 deselected |

Targeted Phase 8 coverage passed:
`uv run --extra config pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/stores/test_deferred_finalization.py tests/contracts/test_deferred_finalization_contract.py tests/integration/pipeline/test_authority_deployment_profiles.py -q`.

## Assumptions And Risks

- Preflight records are deterministic contracts; they do not probe real HPC
  networks or schedulers yet.
- Reconciliation uses the existing public authority operations. A durable
  service backend can later collapse validation and commit into a backend-native
  transaction.
