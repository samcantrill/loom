## Summary

Adds import-light executor descriptor and capability validation contracts for runtime options. The new runtime capability layer can resolve selected executor names, inspect executor resource support metadata, and report deterministic diagnostics for unknown executors, ignored or unsupported resources, and unclaimed adapter namespaces without constructing executors or importing diagnostics/preflight code.

This phase also adds the metadata-only default `local` descriptor, immutable descriptor registry composition, public runtime/pipeline facade exports, focused descriptor documentation, and package/unit/contract/integration coverage for the Phase 5 contracts.

## Acceptance Criteria

- [x] Runtime validation can inspect executor capabilities without constructing executor implementations.
- [x] Unknown selected executors produce error diagnostics and make `CapabilityValidationResult.ok` false.
- [x] Local `cpu`, `memory`, and `gpu` requests warn as ignored/not enforced without failing validation.
- [x] Unclaimed run-level and stage-level adapter namespaces warn without payload inspection.
- [x] Resource capability metadata carries support level, enforcement expectation, severity, and deterministic details.
- [x] Fake descriptors can claim, advise, ignore, or reject registered resource kinds without changing `ResourceRequest`.

## Implementation Notes

- Added `src/loom/pipeline/runtime/capabilities.py` with `ExecutorDescriptor`, `ResourceCapability`, `CapabilityDiagnostic`, `CapabilityValidationResult`, `ExecutorDescriptorRegistry`, `DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY`, `resolve_executor_descriptor()`, and `validate_executor_capabilities()`.
- Kept descriptor behavior below the runtime boundary: no concrete executor, diagnostics, preflight, CLI/config, runner, store, plugin, or optional backend imports.
- The default registry contains only a metadata-only `local` descriptor. `RunOptions.executor=None` resolves to `local` for capability validation, while explicit unknown or whitespace-only names return `executor.unknown` diagnostics.
- Capability diagnostics remain runtime-local records, not preflight check results. Phase 6 still owns check IDs, groups, strict-mode escalation, CLI/config mapping, and user-facing preflight output.
- Adapter namespace validation is ownership-only in this phase and intentionally does not inspect, validate, redact, or persist adapter payloads.

New tests implemented:

- Package tests for runtime/pipeline public exports and import-light boundaries.
- Unit tests for capability record serialization, descriptor normalization, registry determinism/composition, default local policy, unknown executor errors, resource support severities, adapter namespace warnings, diagnostic ordering, and `raise_for_errors()`.
- Contract tests for plain-data descriptor/diagnostic records, fake descriptor/resource registry interaction, independence from diagnostics/preflight IDs, import boundaries, and unchanged execution-envelope wiring.
- Integration tests for merged `RunOptions` capability validation, unknown executor failures, custom descriptors, custom registered resource kinds, and adapter namespace ownership warnings.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ran after the implementation refinement pass; phase artifact records Ruff, Pyright, default no-extra pytest, config-extra pytest, and build passing. |
| `make test-summary` | Passed | Reran for PR evidence on 2026-05-07; wrote `build/test-summary.md` with overall status `passed`. |
| GitHub checks | Passed | PR #74 `checks` workflow completed with `SUCCESS` on 2026-05-07. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.24s |
| unit | passed | 539 | 0 | 0 | 1 | 0 | 5.21s |
| contract | passed | 53 | 0 | 0 | 2 | 0 | 1.95s |
| integration | passed | 15 | 0 | 0 | 6 | 12 | 2.05s |
| e2e | passed | 15 | 0 | 0 | 0 | 0 | 5.74s |
| config-extra | passed | 396 | 0 | 0 | 0 | 672 | 15.43s |
| Overall | passed | 1068 | 0 | 0 | 10 | 684 | 35.62s |

## Risks / Follow-Ups

- Local resource requests now warn as ignored capability diagnostics; Phase 6 must decide how those warnings appear in preflight and strict-mode output.
- Built-in descriptors are intentionally limited to `local`; future executor/plugin phases must populate additional descriptors rather than reinterpreting raw resource or adapter data.
- Adapter namespaces are only claimed or unclaimed in this phase. Deeper schema validation remains owned by later adapter/executor phases.
