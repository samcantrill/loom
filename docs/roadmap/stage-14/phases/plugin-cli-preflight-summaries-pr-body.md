## Summary

- Add `loom plugins list` and `loom plugins check` with stable JSON schemas:
  `loom.cli.plugins.list.v1` and `loom.cli.plugins.check.v1`.
- Add plain plugin diagnostics helpers for metadata summaries, selected
  load/check results, duplicate/missing/failure reporting, and listing-only
  future-group labels.
- Add selected `plugins` preflight diagnostics with `plugins.metadata` and
  `plugins.load`, using explicit plugin selectors and scratch recipe/codec
  registries.
- Keep artifact-store backends and other future groups listing-only; Phase 3
  does not add loaders, registry mutation, credential probes, run readiness, or
  provenance persistence.

## Validation

| Check | Result |
| --- | --- |
| Focused Phase 3 pytest paths | passed, 43 tests |
| Touched-path Ruff | passed |
| Touched-path Pyright | passed |
| `make validate-pr` | passed |
| `make test-summary` | passed |

Suite evidence from `make test-summary`:

| Suite | Result |
| --- | --- |
| package | passed: 87 passed, 1 skipped |
| unit | passed: 1117 passed, 7 skipped, 1 deselected |
| contract | passed: 208 passed, 2 skipped |
| integration | passed: 156 passed, 8 skipped, 13 deselected |
| e2e | passed: 43 passed, 2 deselected |
| config-extra | passed: 440 passed, 1620 deselected |

## Assumptions And Risks

- Recipe and codec entry points are the only Stage 14 registry-ready groups.
- `plugins check` fails closed for listing-only groups because Stage 14 cannot
  prove those entries are registered or run-ready.
- Plugin summaries are diagnostic plain data only; persisted provenance schema
  work remains out of scope.
