## Summary

- Added explicit `loom.event_sinks` plugin loading through
  `load_event_sink_entry_points(records, registry, ...)`.
- Marked event sink plugins registry-ready and loadable, including scratch
  registry checks in plugin diagnostics and preflight.
- Updated plugin/CLI/preflight contracts and Stage 20 docs for read-only event
  inspection, callback failure facts, observer links, and deferred broad CLI
  event inspection.

## Tests

| Command | Result |
| --- | --- |
| `uv run pytest tests/unit/loom/plugins/test_entrypoints.py tests/unit/loom/plugins/test_adapters.py tests/unit/loom/plugins/test_diagnostics.py tests/contracts/test_plugin_discovery_contract.py tests/contracts/test_plugin_future_groups_contract.py tests/package/test_plugins_api.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/diagnostics/test_preflight_plugins.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py` | passed, 84 tests |
| `uv run pytest tests/unit/loom/cli/test_plugins.py tests/unit/loom/plugins/test_diagnostics.py tests/unit/loom/diagnostics/test_preflight_plugins.py` | passed, 27 tests |
| `make validate-pr` | passed Ruff, Pyright, default harness, config-extra harness, and build |
| `make test-summary` | passed, overall 2385 passed, 21 skipped, 1961 deselected |

## Notes

- Event sink plugin loading remains explicit and uses supplied registries only.
- Preflight imports selected trusted event sink targets only for scratch
  registration; it does not dispatch events or write observer facts.
- Broad runtime event inspection CLI remains deferred to a future CLI/runtime
  event surface over existing read APIs.
