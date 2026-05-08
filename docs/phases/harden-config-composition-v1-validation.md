# Phase 16 Desired Outcome Validation

This note validates the desired outcomes in
`docs/phases/harden-config-composition-v1.md` against the current tree. It is
intended as review evidence, not as a new product contract.

## Summary

No Phase 16 configuration feature is missing from the implementation. The
configuration surface is implemented through public Python APIs, remains
pipeline-independent, keeps artifact defaults security-first, and has
representative package, unit, contract, integration, and e2e coverage.

The only evidence gap found during this audit was validation freshness:
`build/test-summary.md` may predate the Phase 16 e2e coverage. Rerunning
`make test-summary` refreshes that generated evidence.

## Desired Outcomes

| Desired outcome | Implementation evidence | Test evidence | Status |
| --- | --- | --- | --- |
| Docs describe supported v1 behavior only and label future behavior clearly. | `docs/features/config.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, `docs/features/testing.md` | `tests/integration/docs/test_v0_python_examples.py` validates runnable examples and manifests. | Covered by manual doc audit plus example tests. |
| v1 docs no longer promise `_copy_`. | `_copy_` remains rejected in `src/loom/config/load.py`. | `tests/unit/loom/config/test_load.py`, `tests/unit/loom/config/test_compose.py`, `tests/contracts/test_config_error_contract.py` | Covered. |
| v1 docs no longer promise default raw source snapshots. | `compose_config(..., include_raw_source_snapshots=False)` creates metadata-only snapshot references. | `tests/integration/config/test_compose_source_snapshots.py`, `tests/contracts/test_config_composition_inspection_contract.py`, `tests/e2e/test_config_composition_public_api.py` | Covered. |
| v1 docs no longer promise default resolved-config persistence. | `loom.config` returns composition artifacts but does not write run-store config artifacts. | `tests/package/test_import_boundaries.py`, `tests/integration/config/test_compose_provenance.py` | Covered. |
| Pipeline remains independent from config artifacts. | `loom.config` import boundary is lazy; `loom.pipeline` consumes plain config data. | `tests/package/test_import_boundaries.py` | Covered. |
| Public Python e2e covers representative strict composition. | `tests/e2e/test_config_composition_public_api.py` builds a temporary config tree through `inspect_config_composition` and `compose_config`. | Same e2e test covers base, overlay, nested include, include replacement, strict overrides, recipe catalog, resolver expression, redaction, manifest, provenance, source metadata, fingerprints, and raw snapshot opt-in/default behavior. | Covered. |
| Structured error audit has regression coverage. | Include resolution, include expansion, override parsing/application, interpolation, validation, and loading all use typed config errors with context. | `tests/unit/loom/config/test_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_resolvers.py`, `tests/contracts/test_config_error_contract.py` | Covered. |
| Artifact-safe defaults omit resolver outputs, raw bytes, and full resolved snapshots. | `src/loom/config/fingerprints.py`, `src/loom/config/compose.py`, and artifact metadata preserve authored facts by default. | `tests/integration/config/test_compose_fingerprints.py`, `tests/integration/config/test_compose_source_snapshots.py`, `tests/e2e/test_config_composition_public_api.py` | Covered. |
| Raw source snapshots require explicit opt-in. | `include_raw_source_snapshots` is validated as a bool and defaults to `False`. | `tests/package/test_config_api.py`, `tests/integration/config/test_compose_source_snapshots.py` | Covered. |
| Product-code changes remain narrow. | The Phase 16 implementation notes identify the `CompositionManifest.to_dict()` nested recipe-manifest thawing fix as the only product fix. | `tests/contracts/test_config_artifact_contract.py` | Covered. |
| Examples remain runnable and v1-safe. | `examples/authoring/**` use Python APIs, trusted recipes, and explicit target instantiation. | `tests/integration/docs/test_v0_python_examples.py` | Covered for manifest shape and smoke execution. |

## Additional Coverage Added By This Audit

The follow-up audit identified behavioral gaps that were not missing features
but were useful review hardening:

- composed recipe output that contains nested `_target_` nodes and is later
  passed to `instantiate`;
- public `compose_config` include-cycle error context;
- `loom.config.instantiate` import-boundary behavior without optional
  composition dependencies;
- multi-overlay replacement provenance;
- public redaction behavior for case and punctuation variants;
- public invalid-YAML error context;
- raw source snapshot behavior when overlay replacement and user include
  addition occur together;
- nested `_target_` in `_args_` with runtime injection and child-path failure
  messages.
