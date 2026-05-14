@samcantrill

## Summary

This PR implements Phase 1 of the v2 CLI-core plan by hard-swapping runtime run identity from `run_id` to `run_uri` before command behavior is exposed.

- Adds strict local `file://` run URI helpers and store-owned default run URI allocation.
- Migrates public/protocol/persisted runtime, planning, execution, store, status, event, lock, provenance, and artifact-address surfaces to `run_uri`.
- Keeps `ArtifactRef` run-agnostic and keeps ambient run identity out of stage fingerprints.
- Updates tests, README/example usage, and owning feature docs that would otherwise contradict the new behavior.

## Validation

| Command | Result |
| --- | --- |
| `make validate-pr` | Passed |
| `make test-summary` | Passed; wrote `build/test-summary.md` |

Suite evidence from `make test-summary`:

| Suite | Result |
| --- | --- |
| package | 39 passed, 1 skipped |
| unit | 377 passed, 1 skipped |
| contract | 36 passed, 2 skipped |
| integration | 9 passed, 5 skipped |
| e2e | 7 passed |
| config-extra | 363 passed, 468 deselected |

## Notes

- No compatibility bridge is included for old persisted `run_id` documents; this follows the accepted v2 hard-swap decision.
- Only local run URIs are supported in this phase. Non-local schemes, file authorities, plain paths, query strings, and fragments fail loudly.
- Direct-pushing the local v2 plan-refinement commits to `develop` was blocked by the approval guard, so this branch may carry those base planning commits until `develop` is advanced separately.
