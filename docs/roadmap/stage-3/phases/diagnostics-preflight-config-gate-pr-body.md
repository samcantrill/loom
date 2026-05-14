## Summary

This follow-up resolves the Phase 1 PR review blocker found after PR #65:
the diagnostics integration module used config extras but was not marked for
the `config-extra` validation gate.

The change adds the `optional_dependency` marker to the diagnostics preflight
integration tests so the four config-backed diagnostics checks are collected by
the standard config-extra suite. It also refreshes the Phase 1 evidence notes
with the corrected suite counts.

## Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/diagnostics -m optional_dependency --collect-only` | Passed | Collected the 4 diagnostics integration tests under the optional dependency marker. |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default isolated suite passed with 523 passed and 13 skipped; config-extra passed with 384 passed and 537 deselected; uv build produced sdist and wheel artifacts. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | `build/test-summary.md` reports package 46 passed/1 skipped, unit 429 passed/1 skipped, contract 39 passed/2 skipped, integration 9 passed/6 skipped, e2e 14 passed, and config-extra 384 passed/537 deselected. |

## Scope

- Runtime behavior is unchanged.
- The follow-up is limited to the suite marker fix and Phase 1 evidence docs.
- No Phase 2 CLI preflight or later status/log/artifact diagnostics work is
  included.
