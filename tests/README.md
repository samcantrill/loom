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
