# CLI Core - Phase 2: Foundation and Shared Output

## Summary

Adds the command-neutral v2 CLI foundation:

- `loom` console script entry point and import-light `main(argv)`.
- Help/version behavior and argparse exit-code preservation.
- Placeholder `validate`, `plan`, and `run` parser registrations without implementing command behavior early.
- Shared output format, warning/result payload, JSON envelope, error payload, exit-code, and traceback helpers.
- Package/import tests proving CLI help does not load config, pipeline, stores, project code, plugins, or optional backends.

## Scope Notes

- Functional `loom validate`, `loom plan`, and `loom run` behavior remains deferred to later phases.
- JSON command-handler errors are emitted to stdout when a parsed command has `--format json`.
- Argparse usage errors remain text on stderr.

## Validation

| Check | Result |
| --- | --- |
| `uv run pytest tests/unit/loom/cli tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_public_api.py -q` | Passed, 43 passed |
| `uv run ruff check .` | Passed |
| `uv run --extra config pyright` | Passed, 0 errors |
| `make validate-pr` | Passed |
| `make test-summary` | Passed, overall 850 passed, 9 skipped, 487 deselected |

## Risks

- Placeholder commands intentionally return structured unsupported-command errors until their implementation phases land.
- CLI result dataclasses are presentation wrappers only; later phases should map real subsystem results into them rather than moving config, planning, or execution logic into `loom.cli`.
