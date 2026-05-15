# Phase 3 Execution Plan: Immutable Artifact Semantics

## Metadata

- Status: final phase execution plan; implementation not started
- Feature focus: External Artifact Interface
- PR title: `External Artifact Interface - Phase 3: Immutable Artifact Semantics`
- Branch: `codex/immutable-artifact-semantics`
- Worktree: `/home/samcantrill/work/loom-worktrees/immutable-artifact-semantics`
- Phase execution plan path:
  `docs/roadmap/stage-15/phases/immutable-artifact-semantics.md`
- Full plan: `docs/roadmap/stage-15/implementation-plan.md`
- Source phase: Phase 3, `immutable-artifact-semantics`
- Stack predecessor: none; Phase 2 is merged
- Base branch: `develop` at `d5ff8efc18963f0c41385c64c9d645895be2b411`
- Target branch: `develop`
- Merge eligibility: root PR may merge to `develop` after implementation,
  validation, PR preparation, automated review, and GitHub merge checks.
- Workflow path: expanded path because this phase connects public artifact
  records to store-owned backend handlers and lookup behavior.
- Successor dependency notes: Phase 4 should branch from this phase branch only
  if this phase PR cannot merge; otherwise branch from updated `develop`.
- Plan quality gate: passed in the implementation plan; Phases 1 and 2 are
  merged and recorded.
- Plan quality gate loop budget: used by the implementation plan gate.
- Draft pass: complete in this artifact.
- Refine pass: complete in this artifact; helper API boundaries and planner
  non-integration stop conditions were tightened.
- Setup limitations: no product checks were run during planning.
- Blockers: none.

## Objective

Add metadata-only immutable artifact semantics over the Phase 1 records and
Phase 2 backend contracts: declaration validation, published-record validation,
fail-closed capability admission, explicit lookup helpers, and conversion to
legacy `ArtifactRef` records without payload movement.

## Full-Plan Context

Phase 1 created artifact records and Phase 2 created backend contracts. Phase 3
turns those records into explicit helper behavior, but must not change planner
reuse, runner wiring, preflight, catalog/bundle preservation, Stage 12 exchange,
or any payload publish/download/materialization behavior. Phases 4-6 consume
these helpers for diagnostics, exchange metadata, and docs/examples.

## Stack Context

- Root or stacked phase: root phase after Phase 2 merge.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phase 2 merged to `develop`, and no
  unmerged Stage 15 predecessor remains.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: delete after merge if no successor depends on it.

## Source Phase Summary

- Goal: implement external immutable input declaration/registration, published
  immutable output semantics, explicit lookup, validation-policy comparison,
  and selected operation admission.
- Required scope: artifact/store helper module, store exports, targeted unit
  and contract tests.
- Required checkpoints: metadata-only validation without handlers, handler
  validation without payload probes, explicit compatible/incompatible/missing/
  unsupported lookup, unknown/unsupported capability fail-closed behavior, and
  no automatic planner cache lookup.
- Acceptance criteria: selected writes/publish/lookup fail closed on missing,
  unknown, or unsupported capabilities; lookup is opt-in; external/published
  records can project to `ArtifactRef` without credentials or network access.

## Current Source And Harness Findings

- `loom.artifacts` remains import-light and already owns
  `ExternalArtifactDeclaration`, `PublishedArtifactRecord`,
  `ImmutableArtifactLookupRequest`, and `ImmutableArtifactLookupResult`.
- `loom.pipeline.stores.artifact_backends` owns handler protocols, capabilities,
  operation results, and diagnostics.
- Store modules may import `loom.artifacts`, but `loom.artifacts` must not
  import stores or plugins.
- Existing planner tests should remain unchanged; this phase must prove lookup
  is explicit helper behavior rather than planner-owned automatic reuse.

## In-Scope Work

- Add a focused store helper module, likely
  `loom.pipeline.stores.immutable_artifacts`, and re-export its public helpers.
- Add `ImmutableArtifactValidationResult` and a small validation target enum for
  plain-data summaries.
- Add helpers to validate external declarations and published records against
  optional handlers and required operations without payload access.
- Add fail-closed operation admission over handlers/capability sets for selected
  read/write/publish/lookup/materialize operations.
- Add explicit lookup helpers that convert handler unsupported/unknown results
  into `ImmutableArtifactLookupResult(status="unsupported", ...)`.
- Add request-vs-published-record comparison for compatible, incompatible, and
  missing results using reuse key, artifact type/schema, checksum, fingerprint,
  and codec validation-policy fields.
- Add conversion helpers from external/published records to `ArtifactRef` for
  metadata-only registration flows.
- Add unit/contract/package tests for the helper behavior and exports.

## Out-of-Scope Work

- Automatic planner/global cache lookup or partial stage reuse.
- Runner artifact-store wiring or replacement.
- Payload publish, upload, download, materialization, deletion, or retention
  cleanup.
- Preflight check IDs, catalog/bundle preservation, or Stage 12 exchange
  changes.
- Real backend adapters, SDK imports, network probes, credential probes, or
  domain-specific artifact schemas.

## Assumptions

- Metadata-only validation without a handler is accepted and records that no
  backend was consulted.
- Capability admission is the fail-closed path for selected operations; record
  validation alone does not prove operation readiness.
- Validation-policy comparison enforces only generic keys that core can
  understand: `checksum`, `fingerprint`, and `codec_key`.
- Handler `check()` is not called by default because Phase 3 should avoid
  accidental readiness/probe semantics; Phase 4 owns preflight checks.

## Scope Contract

- Public helpers live under `loom.pipeline.stores` and may import public
  artifact records plus artifact backend contracts.
- `validate_external_artifact_declaration(...)` and
  `validate_published_artifact_record(...)` return strict validation-result
  records and never move payloads.
- `admit_artifact_store_operation(...)` returns `None` only for known-supported
  operations; missing handlers, unsupported operations, and unknown support
  return structured operation results.
- `lookup_immutable_artifact(...)` is explicit and returns
  `ImmutableArtifactLookupResult`; it does not run unless called.
- `evaluate_immutable_artifact_lookup(...)` compares an explicit request with
  an optional published record and returns compatible, incompatible, or missing.
- Conversion helpers to `ArtifactRef` preserve old ref compatibility while
  embedding external/published summaries in metadata.

## Design Impact

- Maintainability: semantics are store helpers over stable records/contracts,
  avoiding planner or runner coupling.
- Extensibility: optional handlers can implement lookup later while core keeps
  unsupported/unknown results stable.
- Domain neutrality: reuse keys and validation policies remain generic project
  strings and digest fields.
- Source-tree boundaries: `loom.artifacts` remains store/plugin-free; stores do
  not import run exchange, diagnostics, or plugins.

## Future Compatibility

Stage 16 can materialize compatible lookup results explicitly. Stage 19 can add
retry/probe behavior around handlers. Stage 20 can consume retention hints
without Stage 15 adding deletion behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Planner-owned automatic lookup | Violates the explicit lookup decision and risks hidden cross-run reuse. |
| URI scheme as capability proof | Capabilities are operation-specific and handler-owned. |
| Mandatory checksum/credential probes | Metadata-only declarations must remain valid without payload or credential access. |
| Adding helper imports to `loom.artifacts` | Would break the import-light artifact record boundary. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Generic validation-policy keys are intentionally narrow | Avoids domain schemas and real-adapter assumptions | First optional backend needs a generic policy field core cannot compare |
| Missing handler admission returns unknown rather than typed backend-specific errors | Keeps metadata-only records valid while selected operations fail closed | Phase 4 preflight needs richer configured-backend diagnostics |

## Reviewability

- Expected PR size and shape: one store helper module, exports, tests, phase
  artifact, and PR body.
- Files and areas to inspect: immutable helper semantics, capability admission,
  explicit lookup conversion, artifact-ref projection tests.
- Scope-control checks: no planner lookup calls, no runner wiring, no preflight
  or run-exchange code, no payload I/O.

## Implementation Steps

1. Add immutable artifact validation/admission/lookup helper module under
   stores.
2. Add `ArtifactRef` projection helpers for external declarations and published
   records.
3. Export the helper names from `loom.pipeline.stores` and update package
   export tests.
4. Add unit tests for validation, capability admission, lookup outcomes, and
   metadata-only flows.
5. Add contract tests proving explicit lookup and fail-closed selected
   operations with fake handlers.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: public exports and import boundaries.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/stores`,
  `tests/unit/loom/test_artifacts.py` if ref projection coverage belongs there.
- Required assertions or deferral reason: metadata-only validation, handler
  validation, admission, lookup, and projection helpers.

### Contract Suite

- Status: required.
- Expected paths: new
  `tests/contracts/test_immutable_artifact_semantics_contract.py`.
- Required assertions or deferral reason: explicit compatible/incompatible/
  missing/unsupported lookup and fail-closed selected operations.

### Integration Suite

- Status: deferred for new focused coverage.
- Expected paths: none.
- Required assertions or deferral reason: no runner/preflight/catalog/bundle
  integration in Phase 3.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: no CLI workflow changes.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: no service-backed or network suites.

## Risks

- Helper names could imply payload registration. Use metadata/projection wording
  and tests that prove no handler lookup happens unless called.
- Validation policies may look like general schema validation. Keep comparison
  limited to generic artifact facts.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom tests/unit/loom/pipeline/stores tests/contracts/test_immutable_artifact_semantics_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Safe implementation slices: store helper records/functions, exports, unit
  tests, contract tests.
- Tests to run with each slice: new unit/contract tests first, then package
  import/export tests.
- Decisions not to revisit: no automatic lookup, no payload ops, no preflight,
  no run exchange, no service adapters.
- Stop conditions: helper behavior requires runner/planner integration, network
  probes, credential handling, or domain-specific policy schemas.

## Refinement And Review Budget Status

- Phase execution plan draft: complete.
- Phase execution plan refine: complete.
- Phase implementation refinement: unused.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: complete.
- Final phase execution plan: complete.
- Implementation summary: not started.
- Implementation validation: not run.
- Refinement summary: none.
- Blocker-resolution summary: none.
- PR preparation: not started.
- Stack maintenance: Phase 2 merged; no predecessor.
- Remaining blockers: none.
