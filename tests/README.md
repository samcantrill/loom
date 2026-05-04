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
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-summary
make validate-pr
```

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
