# Tests

Tests are grouped by intent.

```text
tests/
  unit/         source-mirrored tests for code under src/loom
  package/      package import, metadata, public API, and typing-marker tests
  integration/  tests that combine multiple loom components
  e2e/          full behavior tests through public APIs or CLI
  contracts/    reusable extension-point behavior tests
  support/      generic test helpers, fixtures, and dummy implementations
```

Unit tests should mirror `src/loom` below `tests/unit/loom`. For example,
`src/loom/pipeline/planning/planner.py` is tested by
`tests/unit/loom/pipeline/planning/test_planner.py`.

Integration and e2e tests must remain domain-neutral. Use dummy stages, local
temporary directories, and public APIs unless a test explicitly needs CLI
execution.

Use the Makefile harness for suite runs:

```sh
make test
make test-help
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-unit-summary
make test-summary
make validate-pr
```

Summary targets run the selected suite with JUnit XML and coverage artifacts
under `build/test-summary/`, then write Markdown tables with pass, failure,
error, skip, deselection, duration, and informational coverage totals. Use
`make test-<suite>-summary` for a focused report or `make test-summary` for all
groups.

Contract tests are executable compatibility checks for Loom extension points.
They should cover protocol and behavior expectations for codecs, sources,
stages, executors, stores, recipes, and future plugin-style extension surfaces.
Support modules are not a runnable suite; `tests/support` holds trusted
test-only helpers and synthetic implementations that are validated through the
package, unit, contract, integration, and e2e suites that consume them.

Empty future suite directories are reported as `not present` by suite-specific
targets. Once a suite contains tests, target failures should be treated as phase
blockers unless the phase plan or PR body explicitly justifies the limitation.

## Validation split for optional dependencies

Phase 1 splits validation into two install surfaces:

- `test-no-extra` (default target): run baseline checks without `loom[config]`
  extras in an isolated environment.
- `test-config-extra`: run config-marked package/unit/integration/docs tests with
  `--extra config` in a separate isolated environment.

`make test-summary` documents both rows so reviewers can see executed config
evidence versus default no-extra evidence. The summary e2e row runs with
`loom[config]` when the public workflow under test is config-backed.
