## Summary

- Add public plugin group readiness metadata so recipes/codecs are the only
  `registry-ready` groups and every future group is explicitly
  `listing-only`.
- Lock future-group behavior in CLI, preflight, package, unit, and contract
  tests: future groups list as metadata, `plugins check` fails closed without
  importing targets, and selected preflight skips loading with listing-only
  details.
- Update plugin feature docs with the current source recheck, readiness table,
  and artifact-store backend boundary.

## Validation

| Check | Result |
| --- | --- |
| Focused Phase 4 pytest paths | passed, 53 tests |
| Touched-path Ruff | passed |
| Touched-path Pyright | passed |
| `make validate-pr` | passed |
| `make test-summary` | passed |

Suite evidence from `make test-summary`:

| Suite | Result |
| --- | --- |
| package | passed: 87 passed, 1 skipped |
| unit | passed: 1131 passed, 7 skipped, 1 deselected |
| contract | passed: 210 passed, 2 skipped |
| integration | passed: 156 passed, 8 skipped, 13 deselected |
| e2e | passed: 43 passed, 2 deselected |
| config-extra | passed: 440 passed, 1636 deselected |

## Assumptions And Risks

- Current `RunExporter`/`RunImporter` and sweep provider protocols are not
  treated as plugin-loader contracts until their owning subsystems expose
  registries or adapter-loading APIs.
- `loom.artifact_store_backends` remains metadata-only until Stage 15 defines
  backend descriptors, registry, config, capability, credential, URI, and
  operation semantics.
- No future-group targets are imported, constructed, registered, or described
  as run-ready in this phase.
