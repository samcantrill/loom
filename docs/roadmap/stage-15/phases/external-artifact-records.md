# Phase 1 Execution Plan: External Artifact Records

## Metadata

- Status: final phase execution plan; implementation not started
- Feature focus: External Artifact Interface
- PR title: `External Artifact Interface - Phase 1: External Artifact Records`
- Branch: `codex/external-artifact-records`
- Worktree: `/home/samcantrill/work/loom-worktrees/external-artifact-records`
- Phase execution plan path:
  `docs/roadmap/stage-15/phases/external-artifact-records.md`
- Full plan: `docs/roadmap/stage-15/implementation-plan.md`
- Source phase: Phase 1, `external-artifact-records`
- Stack predecessor: none; root phase
- Base branch: `develop` at `1ec6cd93c6722fbbd5ad72eab48eb773887187e1`
- Target branch: `develop`
- Merge eligibility: root phase PR is eligible to target `develop` after
  implementation, phase validation, PR preparation, automated review, and CI
  gates pass; planning-only branch is not merge-ready.
- Workflow path: expanded path because this phase creates public persisted
  artifact records and compatibility contracts.
- Successor dependency notes: Phase 2 should branch from this phase branch only
  if this phase PR is open/prepared and not merged; otherwise Phase 2 should
  branch from updated `develop`.
- Plan quality gate: passed on 2026-05-15 in the implementation plan. Evidence
  records local review, refinement, and confirmation with no remaining
  planning-readiness, design-safety, or plan-quality blockers.
- Plan quality gate loop budget: review used, refinement used, confirmation
  used by the implementation-plan gate.
- Draft pass: complete in this artifact after reading AGENTS, workflow,
  template, Stage 15 planning and implementation plan, structure/glossary, and
  current artifact source/tests.
- Refine pass: complete in this artifact for expanded-path public API planning;
  the refine pass tightened field boundaries, suite obligations, stop
  conditions, and Stage 2+ exclusions.
- Setup limitations: no product checks were run during planning; this pass only
  created the branch/worktree, verified the authored Stage 15 artifacts matched
  their landed `develop` copies, reconciled the branch to current `develop`,
  and wrote this phase execution plan.
- Blockers: none.

## Objective

Add backend-neutral, strict plain-data artifact records for external immutable,
published immutable, and multi-location artifact semantics while preserving the
existing `ArtifactRef` dictionary contract and import-light `loom.artifacts`
boundary.

## Full-Plan Context

Stage 15 establishes the external artifact interface contract before any real
backend or payload movement work. Phase 1 owns the broadly reusable record
surface in `loom.artifacts`: location kinds and summaries, store references,
external declarations, published immutable records, and lookup request/result
records. Later phases consume these records for backend registries, immutable
registration/lookup behavior, diagnostics, catalogs, bundles, Stage 12 exchange
metadata, examples, and docs.

Future-phase work that must remain out of this PR: backend descriptors,
registries, handlers, plugin adapters, preflight checks, catalog or bundle
rewrites, Stage 12 exchange changes, real adapters, network/credential probes,
payload upload/download/materialization, cleanup, retention deletion, and
automatic planner reuse.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none recorded.
- Why this base branch is correct: the implementation plan has all phases
  pending and no earlier unmerged Stage 15 phase exists, so the root PR should
  branch from and target `develop`.
- Retarget/rebase plan after predecessor merge: not applicable for this root
  phase. If implementation begins after `develop` moves, the executor or
  manager should rebase the phase branch onto updated `develop` before PR
  preparation.
- Branch cleanup constraints: delete the branch only after the Phase 1 PR is
  merged and no successor branch depends on it.

## Source Phase Summary

- Goal: define strict, backend-neutral artifact value objects for external,
  published, and multi-location semantics while keeping old `ArtifactRef`
  behavior compatible.
- Required scope: `ArtifactLocationKind`, `ArtifactLocationSummary`,
  `ArtifactStoreRef`, `ExternalArtifactDeclaration`,
  `PublishedArtifactRecord`, `ImmutableArtifactLookupRequest`,
  `ImmutableArtifactLookupResult`, summary projection helpers, strict
  unknown-field handling, redacted display fields, and package/unit/contract
  tests.
- Required checkpoints: prove old `ArtifactRef` dictionaries still load; prove
  new summaries are strict plain data; prove secret-bearing core fields are not
  accepted as persisted display values; prove `loom.artifacts` remains
  import-light.
- Acceptance criteria: public records round trip through `to_dict` and
  `from_dict`; invalid enum values, unknown fields, non-plain metadata,
  malformed digests, and unsafe core values fail deterministically; location
  summaries distinguish authoritative external/published facts from derived
  cache/staging/materialized facts; no backend/store/preflight/catalog behavior
  enters this phase.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/artifacts.py` currently exports `ArtifactAddress`,
    `ArtifactRef`, and `ArtifactValidationError`. It imports only foundational
    errors, fingerprints, ids, serialization, and timestamps.
  - `ArtifactRef.from_dict` accepts only `artifact_id`, `uri`,
    `artifact_type`, optional `codec_key`, `schema_version`, `checksum`,
    `fingerprint`, `producer_stage`, `created_at`, and `metadata`. Unknown
    top-level fields are rejected.
  - `ArtifactRef.metadata` already freezes plain data and `to_dict` returns a
    mutable thawed copy.
  - `src/loom/serialization/plain.py` and `src/loom/serialization/schema.py`
    provide plain-data and strict field/version helpers that should be reused
    where they reduce repeated validation.
  - `src/loom/pipeline/stores/artifact_store.py` imports `ArtifactRef` but
    stores remain out of scope for Phase 1.
- Existing tests or harness behavior:
  - `tests/unit/loom/test_artifacts.py` covers `ArtifactRef` and
    `ArtifactAddress` round trips, unknown-field rejection, digest validation,
    metadata immutability, and no loading behavior.
  - `tests/package/test_public_api.py`, `tests/package/test_import.py`, and
    `tests/package/test_import_boundaries.py` cover package exports and
    import-light boundaries.
  - There is no existing external artifact record contract test; Phase 1 should
    add one under `tests/contracts`.
- Import-boundary or dependency constraints:
  - `loom.artifacts` must not import stores, diagnostics, plugins, runs, CLI,
    optional backend SDKs, or network clients.
  - New records must be usable by stores, diagnostics, catalogs, and run
    exchange later through plain dictionaries without importing those layers.

## In-Scope Work

- Add strict public records in `loom.artifacts` or in one adjacent import-light
  module re-exported through `loom.artifacts` if file size becomes a review
  problem.
- Keep existing `ArtifactRef` fields and unknown-field rejection unchanged.
- Add `__all__` exports from `loom.artifacts` for new record names. Root
  `loom.__all__` should remain unchanged unless implementation reveals a
  strong package-policy reason to expose the new records there.
- Implement strict `to_dict` and `from_dict` for each new record with
  `schema_version == 1`, required-field checks, unknown-field rejection,
  frozen internal plain data, and thawed output dictionaries.
- Add location/store/external/published/lookup summary projection helpers that
  return plain data suitable for future metadata, catalog, bundle, and run
  exchange use without choosing those embedding keys in this phase.
- Add tests for package exports, import boundaries, unit validation, old
  `ArtifactRef` compatibility, and public contract behavior.

## Out-of-Scope Work

- Backend descriptors, factories, registries, handlers, fake backends, or
  capability records owned by `loom.pipeline.stores`.
- Plugin loading, entry point normalization, or changes to Stage 14
  listing-only artifact-store backend diagnostics.
- Preflight check IDs, backend availability checks, catalog projections, bundle
  preservation, or Stage 12 portable-run exchange changes.
- Payload materialization, existence probes, checksum probes against remote
  payloads, uploads, downloads, deletion, cleanup, retention actions, or real
  service integrations.
- Automatic global cache lookup, planner reuse behavior, domain-specific
  artifact schemas, or provider-specific permanent fields in core records.

## Assumptions

- Adjacent strict records are sufficient for Phase 1; no `ArtifactRef`
  top-level schema revision is planned.
- Redacted display fields are caller-supplied safe strings in Phase 1. This
  phase validates that unsafe values are not placed in core persisted fields,
  but it does not implement backend-specific redaction or secret scanning.
- Backend-specific metadata is allowed only under `details` mappings that are
  plain data, namespaced by backend conventions, and never required for core
  behavior.
- Any timestamp field added for producer or publication facts should reuse the
  existing UTC timestamp validation style from `ArtifactRef`.

## Scope Contract

Public behavior and data shapes the executor must preserve:

- `ArtifactLocationKind` is a string enum with these serialized values:
  `managed`, `external_immutable`, `published_immutable`, `staging`, `cache`,
  and `materialized`.
- Location authority is represented as a strict field named `authority` with
  values `authoritative` or `derived`. `managed`, `external_immutable`, and
  `published_immutable` locations may be authoritative. `staging`, `cache`,
  and `materialized` locations are derived unless a later phase changes the
  contract.
- `ArtifactStoreRef` serialized fields:
  `schema_version`, `kind`, `key`, `uri`, `display_uri`, and `details`.
  `kind` is required. `key`, `uri`, and `display_uri` are optional non-empty
  strings when present. `display_uri` is the only shareable display form when
  the source URI might contain secrets. `details` is optional plain data and
  defaults to an empty mapping.
- `ArtifactLocationSummary` serialized fields:
  `schema_version`, `kind`, `authority`, `uri`, `display_uri`, `store`,
  `checksum`, `fingerprint`, `size_bytes`, and `details`. `store` is either an
  `ArtifactStoreRef` summary or null. `checksum` and `fingerprint` use existing
  digest validation. `size_bytes` is null or a non-negative integer.
- `ExternalArtifactDeclaration` serialized fields:
  `schema_version`, `artifact_id`, `uri`, `artifact_type`, `codec_key`,
  `artifact_schema_version`, `store`, `location`, `checksum`, `fingerprint`,
  `immutability`, `metadata`, and `details`. `immutability` is a required
  value from `declared` or `validated`; it is not inferred from URI scheme.
- `PublishedArtifactRecord` serialized fields:
  `schema_version`, `artifact_id`, `uri`, `artifact_type`, `codec_key`,
  `artifact_schema_version`, `producer_run_uri`, `producer_stage`,
  `producer_artifact_id`, `reuse_key`, `validation_policy`, `owner`,
  `retention`, `evidence`, `store`, `location`, `metadata`, and `details`.
  `reuse_key` is a project-supplied generic string, not a domain schema.
- `ImmutableArtifactLookupRequest` serialized fields:
  `schema_version`, `reuse_key`, `artifact_type`, `artifact_schema_version`,
  `validation_policy`, `store`, and `details`.
- `ImmutableArtifactLookupResult` serialized fields:
  `schema_version`, `status`, `request`, `published`, `location`,
  `diagnostics`, and `details`. `status` is one of `compatible`,
  `incompatible`, `missing`, or `unsupported`.
- `validation_policy`, `owner`, `retention`, `evidence`, `metadata`, and
  `details` are strict plain-data mappings. Core behavior must not require
  backend-specific keys inside these mappings.
- All new `from_dict` methods reject unknown top-level fields and missing
  required fields. All new records reject non-plain mappings, malformed digests,
  invalid enum values, negative sizes, empty required strings, and boolean
  values where integers are required.
- Existing `ArtifactRef.to_dict` output and `ArtifactRef.from_dict` accepted
  fields remain unchanged. If implementation proves this prevents a required
  guarantee, stop for manager review rather than adding a broad `ArtifactRef`
  schema revision in the executor pass.

## Design Impact

- Maintainability: the phase expands the public artifact record surface but
  keeps behavior local to strict value objects and tests. Validation helpers
  should be shared only when they reduce clear duplication.
- Extensibility: later store, diagnostic, catalog, bundle, and exchange phases
  can consume the same plain summaries without importing backend objects or
  optional packages.
- Domain neutrality: field names describe generic artifact identity, store
  references, validation facts, producer provenance, and location meaning; no
  MLflow, DVC, S3, cloud, model, dataset, checkpoint, or metric semantics are
  required by core.
- Source-tree boundaries: `loom.artifacts` remains foundational. Store
  contracts may later import these records, but this phase must not make
  artifacts import stores, plugins, diagnostics, runs, or CLI.

## Future Compatibility

- Stage 2 can attach backend descriptor/handler contracts to `ArtifactStoreRef`
  and namespaced `details` without changing the Phase 1 serialized keys.
- Stage 3 can add external declaration and published record registration and
  lookup behavior over these records without making lookup automatic.
- Stage 4 and Phase 5 can embed these summaries in diagnostics, catalogs,
  bundles, and portable-run exchange as metadata-only records.
- Stage 16 materialization can add explicit payload movement using derived
  `staging`, `cache`, and `materialized` locations without making those
  locations authoritative.
- Stage 20 cleanup/retention can consume owner/retention hints later; Phase 1
  records hints only and performs no deletion or lifecycle behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put all external, published, and location semantics into untyped `ArtifactRef.metadata` | Weakens validation and makes future catalog/bundle/exchange behavior ambiguous. |
| Broadly add external/published fields to every `ArtifactRef` top-level schema now | Risks persisted compatibility and makes all produced-output refs remote-aware before adjacent records are proven insufficient. |
| Put backend references and capabilities under `loom.pipeline.stores` in Phase 1 | Store behavior and capabilities are Phase 2 scope; Phase 1 records must be reusable without store imports. |
| Use URI scheme as location kind or capability proof | URI schemes cannot express immutability, authority, backend availability, or operation support. |
| Add service-specific fields for MLflow-like or object-store examples | Violates the generic core contract; backend-specific facts belong in namespaced plain `details`. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Adjacent records require callers to carry `ArtifactRef` plus summaries | Preserves old `ArtifactRef` compatibility while adding typed validation | A later phase cannot enforce location semantics or stable summary projection without a narrow top-level `ArtifactRef` revision |
| Redaction is represented by persisted `display_uri` fields but backend-specific redaction is deferred | Phase 1 has no backend handlers or config ownership | Phase 2 or 4 needs deterministic redaction hooks for configured backends |
| Validation policy remains a plain-data mapping rather than a separate public record | Keeps Phase 1 focused on confirmed record names while allowing Stage 3 to harden behavior | Repeated policy validation becomes complex or lookup/register behavior needs stronger typed policy semantics |

## Reviewability

- Expected PR size and shape: one artifact-record implementation slice plus
  package/unit/contract tests. The PR should not touch execution, stores,
  diagnostics, plugins, runs, CLI behavior, or feature docs except if brief
  docstrings are needed for public records.
- Files and areas to inspect: `src/loom/artifacts.py` or a new adjacent
  import-light artifact-record module, `tests/unit/loom/test_artifacts.py`,
  a new contract test under `tests/contracts`, and package/import-boundary
  tests under `tests/package`.
- Scope-control checks: no imports from `loom.pipeline`, `loom.plugins`,
  `loom.diagnostics`, `loom.runs`, or optional SDKs in artifact record modules;
  no `ArtifactStore` registry or preflight check IDs; no payload access; old
  `ArtifactRef` tests remain valid.

## Implementation Steps

1. Add the record types and validation helpers in the artifact layer, keeping
   imports foundational and schemas strict.
2. Add serialization and summary projection behavior for store refs, location
   summaries, external declarations, published records, and lookup
   request/results.
3. Extend unit tests for valid/invalid records, strict unknown-field behavior,
   immutable internal plain data, digest/timestamp/size validation, and old
   `ArtifactRef` compatibility.
4. Add contract tests that lock the public serialized field names, status/kind
   values, adjacent-record composition with `ArtifactRef`, and metadata-only
   summary behavior.
5. Update package export/import-boundary tests for `loom.artifacts` symbols and
   to prove no stores, plugins, diagnostics, runs, CLI, optional SDKs, or
   network paths are imported by the artifact layer.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_public_api.py`,
  `tests/package/test_import.py`, and
  `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: verify new records are importable
  from `loom.artifacts`, `loom.artifacts.__all__` includes them, root
  `loom.__all__` remains intentionally unchanged unless changed with a recorded
  reason, and `import loom.artifacts` does not import stores, diagnostics,
  plugins, runs, CLI, optional backend SDKs, or config extras.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/test_artifacts.py` and any small focused
  artifact unit file if the test file becomes too large.
- Required assertions or deferral reason: cover happy-path round trips,
  unknown-field rejection, missing required fields, invalid enum/status values,
  malformed checksums/fingerprints, negative `size_bytes`, invalid timestamps
  where present, non-plain `metadata`/`details`, immutable internal state,
  thawed `to_dict` copies, and unchanged `ArtifactRef` compatibility.

### Contract Suite

- Status: required.
- Expected paths: new
  `tests/contracts/test_external_artifact_records_contract.py`.
- Required assertions or deferral reason: lock serialized field names,
  `schema_version == 1` policy, `ArtifactLocationKind` values, lookup result
  statuses, authoritative vs derived location semantics, adjacent summary
  projection with an old `ArtifactRef`, redacted display field behavior, and
  absence of backend-specific required fields.

### Integration Suite

- Status: deferred for new focused coverage.
- Expected paths: none for Phase 1.
- Required assertions or deferral reason: Phase 1 adds value objects only and
  does not integrate with stores, diagnostics, catalogs, bundles, run exchange,
  or CLI. Existing integration suites still run as part of `make validate-pr`.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: there is no user workflow, CLI
  command, backend service, or run execution path in Phase 1.

### Opt-In Suites

- Status: deferred.
- Markers affected: no `slurm_acceptance`, service-backed, network, credential,
  container, or optional backend SDK suites should be added or required.
- Required assertions or deferral reason: Phase 1 must remain fake/backend-free
  and metadata-only; opt-in service behavior belongs to later roadmap stages.

## Risks

- Public field names may become hard to change after Phase 2+ consume them.
  Mitigation: contract tests lock only the field names and enum values chosen
  here, and later behavior uses namespaced `details` for backend-specific facts.
- The `loom.artifacts` module may become too large. Mitigation: an adjacent
  import-light module re-exported from `loom.artifacts` is allowed if it keeps
  public imports stable and avoids converting `loom.artifacts` to a package.
- Secret-bearing values could be accidentally persisted in `uri` instead of
  `display_uri`. Mitigation: Phase 1 tests must make the core contract clear:
  shareable output should use `display_uri`; backend redaction mechanics are
  deferred to store handlers.
- Adjacent records may be awkward for callers. Mitigation: summary projection
  helpers and contract tests prove a stable composition path before later
  phases adopt them.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/test_artifacts.py tests/contracts/test_external_artifact_records_contract.py tests/package/test_public_api.py tests/package/test_import.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom tests/contracts tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: artifact value objects first, serialization
  helpers second, tests third, package/import-boundary updates last.
- Tests to run with each slice: start with
  `uv run pytest tests/unit/loom/test_artifacts.py`, then add the new contract
  test and package import tests once public exports exist.
- Decisions the executor must not revisit: no real backends, no backend
  registry, no plugin adapter, no preflight, no catalog/bundle/run-exchange
  changes, no automatic lookup, no service-specific core fields, and no
  `ArtifactRef` top-level schema revision without stopping for manager review.
- Conditions that require stopping for the manager: adjacent records cannot
  provide a concrete required guarantee; the implementation needs imports from
  stores/plugins/diagnostics/runs/CLI; a new dependency appears necessary; a
  public field name in this plan is unusable for compatibility reasons; or
  targeted validation reveals a scope or import-boundary blocker.

## Refinement And Review Budget Status

- Phase execution plan draft: complete.
- Phase execution plan refine: complete; expanded-path refine was used because
  Phase 1 is public persisted API work.
- Phase implementation refinement: not needed; manager completed a scoped
  validation fix after executor shutdown.
- PR review: unused.
- Blocker resolution: 1/3 used for manager-local Pyright/type compatibility
  fixes after the implementation handoff was incomplete.

## Completion Notes

- Draft plan: completed in
  `docs/roadmap/stage-15/phases/external-artifact-records.md`.
- Final phase execution plan: completed in the same artifact after the
  expanded-path refine pass.
- Implementation summary: added strict backend-neutral artifact record types
  (`ArtifactLocationKind`, `ArtifactStoreRef`,
  `ArtifactLocationSummary`, `ExternalArtifactDeclaration`,
  `PublishedArtifactRecord`, `ImmutableArtifactLookupRequest`, and
  `ImmutableArtifactLookupResult`) to `src/loom/artifacts.py` with strict
  `to_dict`/`from_dict` validation, enum/value checks, digest validation,
  non-negative size checks, plain-data freezing/thawing, summary helpers, and
  unknown-field rejection; kept `ArtifactRef` and existing `ArtifactAddress`
  compatibility unchanged.
- Unit coverage: extended `tests/unit/loom/test_artifacts.py` to include strict
  round trips and contract-shape tests for all new record types and to confirm
  `ArtifactRef` metadata immutability/compatibility.
- Package coverage: updated `tests/package/test_public_api.py` and
  `tests/package/test_import_boundaries.py` to assert new record exports from
  `loom.artifacts.__all__` and artifact-module import-light boundaries.
- Contract coverage: added `tests/contracts/test_external_artifact_records_contract.py`
  for serialized field sets, enum values, strict failure cases, and summary
  interoperability across legacy `ArtifactRef` and new records.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/test_artifacts.py tests/contracts/test_external_artifact_records_contract.py tests/package/test_public_api.py tests/package/test_import.py tests/package/test_import_boundaries.py`
    passed: 88 passed in 14.72s.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom tests/contracts tests/package`
    was attempted in the sandbox but hit sandbox socket restrictions in
    `LocalAuthorityService.start()` (`PermissionError: Operation not
    permitted`) and stalled in the larger suite; the same coverage was
    subsequently covered by the escalated PR gate.
  - `make validate-pr` passed outside the sandbox after rerun with approved
    permissions because multiprocessing socket tests are blocked by the
    default sandbox: Ruff passed, Pyright passed with 0 errors, default harness
    passed with 1622 passed / 26 skipped / 18 deselected, config-extra harness
    passed with 440 passed / 1659 deselected, and `uv build` produced the sdist
    and wheel.
- Refinement summary: plan-only refine complete; no separate
  `loom_phase_refiner` pass was used. The manager completed one scoped local
  validation fix to preserve generic store kinds, restore positive-integer
  legacy `ArtifactRef.schema_version` compatibility, and satisfy Pyright.
- Blocker-resolution summary: 1/3 used for the manager-local Pyright/type
  compatibility fix described above.
- PR preparation: not started.
- Stack maintenance: root branch reset to current `develop`
  (`1ec6cd93c6722fbbd5ad72eab48eb773887187e1`) after verifying the local
  Stage 15 planning artifacts matched the landed files; no predecessor.
- Remaining blockers: none.
