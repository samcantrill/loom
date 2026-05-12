## Summary

- Adds an explicit offline-first execution path that writes a versioned, non-authoritative evidence manifest for local runs.
- Introduces strict offline evidence models, manifest read/write helpers, and an offline run-store adapter while preserving the raw `LocalRunStore` rejection in `PipelineRunner`.
- Wires `loom run --offline-first` and `--authority-mode offline_first` through CLI execution, preflight labeling, and JSON/text output summaries.

## Implementation Notes

- Offline evidence is written to `offline-evidence/manifest.json` after terminal runner execution and carries `kind`, schema version, state-source metadata, run/plan/runtime/config/provenance facts, stage status/order, resource requests, artifact facts, logs, and local event evidence.
- The manifest source is explicitly non-authoritative. Online authority-backed runs do not write offline evidence, and online authority resolution/mutation failures do not fall back to local evidence.
- Missing local evidence is represented with structured diagnostics. Missing required run, plan, runtime, or stage facts produce error diagnostics; missing optional logs or payload bytes are warning diagnostics.
- Local payload facts include size and checksum when the referenced payload resolves to a readable local file.

New tests implemented:

- Manifest unit and contract coverage for strict schema/kind validation, diagnostics, event ordering, stage/output/artifact/resource facts, and readable Phase 18 fixture shapes.
- CLI/unit/integration/e2e coverage for explicit offline-first selection, evidence path reporting, and default online behavior staying authority-backed.
- Package API coverage for the additive execution facade exports.

## Tests And Validation

| Command | Result | Evidence |
| --- | --- | --- |
| Targeted Ruff/Pyright/Pytest | Passed | Ruff and Pyright passed on changed implementation/tests; focused pytest passed for manifest, CLI, package, contract, config integration, and e2e offline-first coverage. |
| `make validate-pr` | Passed | Ruff, Pyright, default `1336 passed, 19 skipped, 14 deselected`, config-extra `424 passed, 1366 deselected`, and build succeeded. |
| `make test-summary` | Passed | Suite table below. |
| GitHub checks | Pending | To be recorded after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 70 | 0 | 0 | 1 | 0 |
| unit | passed | 971 | 0 | 0 | 1 | 0 |
| contract | passed | 154 | 0 | 0 | 2 | 0 |
| integration | passed | 128 | 0 | 0 | 8 | 10 |
| e2e | passed | 40 | 0 | 0 | 0 | 2 |
| config-extra | passed | 424 | 0 | 0 | 0 | 1366 |

## Risks / Follow-Ups

- Phase 17 only writes evidence; Phase 18 owns authority import, collision policy, and repository transaction behavior.
- Payload verification is local-file oriented. Remote artifact stores remain represented by metadata and diagnostics until a future importable remote payload contract exists.
- Offline resource evidence is descriptive and does not enforce service-backed resource capacity.
