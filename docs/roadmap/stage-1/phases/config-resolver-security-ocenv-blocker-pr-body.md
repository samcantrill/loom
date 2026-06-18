## Summary

@samcantrill

This follow-up fixes the Phase 8 resolver-security blocker found during post-merge review. Runtime `oc.env` resolution no longer delegates to OmegaConf's mutable global resolver registry; Loom resolves `oc.env` through its own runtime implementation before final node interpolation.

The fix preserves Phase 8 scope: `oc.env` remains the only allow-listed runtime resolver, other built-ins and custom resolvers still fail before execution, resolver outputs are not persisted, and no public config/artifact/CLI/pipeline surface is added.

## Acceptance Criteria

- [x] Replacing OmegaConf's global `oc.env` resolver does not execute project code through `resolve_interpolation()`.
- [x] Public `compose_config()` uses the Loom-owned `oc.env` path even if OmegaConf's global `oc.env` resolver is replaced.
- [x] Environment values that look like interpolation remain literal output and are not reparsed as custom resolvers.
- [x] Phase 8 boundaries remain intact: no public root exports, public `ComposedConfig` fields, manifest/source-artifact/fingerprint/provenance population, CLI behavior, pipeline imports, run-store writes, resolver plugins, remote resolvers, recipe behavior changes, or `_copy_`.

## Implementation Notes

`src/loom/config/interpolation.py` now resolves allow-listed runtime resolver tokens before handing the config to OmegaConf for ordinary node interpolation. The `oc.env` implementation reads from `os.environ` directly and escapes interpolation openings in environment output so the value is treated as literal data.

New regression tests cover both the lower-level interpolation helper and public composition path when the global OmegaConf `oc.env` binding is replaced.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright passed with 0 errors; default suite passed with 426 passed and 9 skipped; config-extra passed with 239 passed and 431 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`. |
| Targeted resolver tests | Passed | `tests/unit/loom/config/test_interpolation.py` and `tests/integration/config/test_compose_resolvers.py`: 18 passed. |
| Broader Phase 8 regression group | Passed | Config errors, error contracts, compose overrides, and import-boundary targets: 37 passed. |
| GitHub checks | Passed | PR #35 `checks` completed successfully. |

## Risks / Follow-Ups

- `oc.env` remains the only runtime resolver admitted in Phase 8.
- Other OmegaConf built-ins and custom resolver APIs remain deferred to later explicit design work.
