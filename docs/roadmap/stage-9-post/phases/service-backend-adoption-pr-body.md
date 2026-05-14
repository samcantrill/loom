## Summary

- Adds shared authority configuration resolution for environment variables, CLI flags, worker command handoff, and runtime store construction.
- Routes run, plan, preflight, status, cancel, stage worker, prepared-run, subprocess, SLURM planning/submission/status, diagnostics, and catalog scan paths through explicit authority config while keeping transitional SQLite as the default.
- Carries redacted authority summaries in worker/submitted metadata and preserves full service references only in trusted handoff/config channels.
- Documents service-backed adoption and updates the subprocess example to exercise explicit co-located service authority.

## Tests

| Command | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default suite, config-extra suite, and `uv build` |
| `make test-summary` | Passed: package 57, unit 855, contract 112, integration 100, e2e 39, config-extra 420 |

## Assumptions And Risks

- Transitional SQLite remains the implicit default until Phase 10.
- The deterministic local service fixture proves service-backed runtime adoption in default validation; real external service and multi-host HPC topology remain opt-in.
- CLI authority metadata is trusted project/runtime configuration, but public diagnostics and manifests use redacted summaries.
