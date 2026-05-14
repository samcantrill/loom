## Summary

- Enables service-backed generic resource limits and resource leases through the authority coordination protocol.
- Adds runner-side resource admission for positive integer runtime resource requests, with fail-fast default behavior, bounded wait settings, structured failure records, and terminal lease release.
- Wires HTTP authority-backed run stores to a service coordination adapter while preserving explicit non-HTTP authority-store construction.

## Tests

| Command | Result |
| --- | --- |
| Targeted `uv run ruff check ...` | Passed |
| Targeted `uv run pyright ...` | Passed |
| Targeted `uv run pytest ...` | 171 passed, 1 skipped |
| `make validate-pr` | Passed: Ruff, Pyright, default 1329 passed/19 skipped/14 deselected, config-extra 423 passed/1358 deselected, build succeeded |
| `make test-summary` | Passed: package 70 passed/1 skipped; unit 967 passed/1 skipped; contract 151 passed/2 skipped; integration 128 passed/8 skipped/10 deselected; e2e 39 passed/2 deselected; config-extra 423 passed/1358 deselected |

## Assumptions And Risks

- Resource admission only leases positive integer amounts. Non-integer runtime resource requests fail before stage launch.
- Bounded wait uses polling over the existing acquire operation; scheduler queues, fairness, and priority are still out of scope.
- There is no resource-specific CLI e2e because this phase does not add a user-facing command to seed service resource limits before `loom run`; service-backed admission is covered by integration tests.
