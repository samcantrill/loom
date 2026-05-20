# Summary

- Updated current user-facing docs, README examples, feature docs, package docs,
  and roadmap metadata so `weave` is the config authoring package and Loom is
  the workflow/runtime package with explicit config adapter paths.
- Updated example coverage and testing docs to point config authoring examples
  at `packages/weave/examples` and to document package-local validation.
- Included `validate-weave` in the combined `make validate-pr` gate so final PR
  validation includes root Loom and package-local `weave` evidence.

# Tests

| Command/check | Result |
| --- | --- |
| `make validate-weave` | Passed: Ruff, Pyright, 375 package tests, 8 package examples, package build. |
| `uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py` | Passed outside sandbox: 33 tests. |
| Active `loom.config` import sweep | Passed: only intentional absence assertions in `tests/package/test_import_boundaries.py`. |
| Active `examples/authoring` / `authoring.` sweep | Passed: no matches. |
| `make validate-pr` | Passed outside sandbox: Ruff, Pyright, default, config-extra, `validate-weave`, root build. |
| `make test-summary` | Passed; wrote package, unit, contract, integration, e2e, config-extra, weave, and weave-examples rows. |

`make test-summary` totals:

| Suite | Status | Passed | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: |
| package | passed | 112 | 0 | 4 |
| unit | passed | 1402 | 0 | 2 |
| contract | passed | 252 | 0 | 8 |
| integration | passed | 170 | 0 | 82 |
| e2e | passed | 46 | 0 | 6 |
| config-extra | passed | 128 | 3 | 1985 |
| weave | passed | 375 | 0 | 0 |
| weave-examples | passed | 8 | 0 | 0 |

# Assumptions And Risks

- Historical roadmap and planning artifacts may still mention `loom.config`
  when describing pre-extraction behavior or the accepted no-shim decision.
- The Stage 23 compatibility debt remains: recipe loading is owned by `weave`,
  but the entry-point group name stays `loom.recipes` until a future standalone
  package or publication phase revisits it.
