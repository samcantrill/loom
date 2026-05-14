## Summary

- Adds an HTTP client-backed per-run authority store for the primary Python runner path.
- Extends the repository-free authority client for controller/stage leases and submitted-operation mutation routes.
- Wires ready HTTP authority references into `create_authority_backed_serial_run_store()` for online `loom run`.
- Keeps audit events local-only until a service audit route exists, while lifecycle, lease, attempt, output, and submitted-operation mutations go through the authority service.

## Tests

| Command | Result |
| --- | --- |
| Targeted Ruff / Pyright for changed source and tests | Passed |
| Targeted pytest for authority client, adapter, mutation API, local execution, supervisor smoke | 26 passed, 2 skipped |
| `tests/package/test_pipeline_store_api.py` | 11 passed |
| `make validate-pr` | Passed: Ruff, Pyright, default 1297 passed / 19 skipped / 14 deselected, config-extra 422 passed / 1326 deselected, build passed |
| `make test-summary` | Passed: package 69 passed / 1 skipped; unit 942 passed / 1 skipped; contract 146 passed / 2 skipped; integration 127 passed / 8 skipped / 10 deselected; e2e 39 passed / 2 deselected; config-extra 422 passed / 1326 deselected |

## Assumptions And Risks

- FastAPI `TestClient` paths hang under the restricted Codex sandbox, so validation gates that exercise those paths were run with approved escalation.
- Worker continuation, SLURM paths, workspace coordination, offline import, and remote artifact storage remain out of scope for later phases.
- HTTP-backed audit events remain local-only until the authority service exposes audit-event mutation/read routes.
