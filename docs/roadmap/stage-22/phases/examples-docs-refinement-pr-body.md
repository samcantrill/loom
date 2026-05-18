## Summary

- Align the top-level README and examples catalog with the current local-first implementation and Stage 22 validation evidence.
- Clarify validation tier wording, group catalog placement, and focused configuration/authority coverage docs without changing runtime behavior.
- Record Phase 4 validation evidence and final Stage 22 manual/internal-demo boundaries in roadmap artifacts.

## Validation

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py tests/e2e/test_example_journeys.py -q` | Passed, `44 passed` |
| `UV_CACHE_DIR=/tmp/uv-cache make test-e2e` | Passed, `46 passed, 6 deselected` |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed: Ruff, Pyright 0 errors, default `1963 passed, 26 skipped, 30 deselected`, config-extra `460 passed, 3 skipped, 2001 deselected`, build succeeded |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed: overall `2452 passed, 21 skipped, 2026 deselected` |

## Assumptions And Risks

- No runtime, CLI, executor, store, authority, plugin, dependency, or external-system behavior changes are included.
- Live SLURM, live Docker, provider, daemon, and network-backed workflows remain manual or opt-in because Stage 22 keeps default validation deterministic and fake/local-backed.
- `internal_demo` examples remain support coverage rather than primary user-facing catalog entries.
