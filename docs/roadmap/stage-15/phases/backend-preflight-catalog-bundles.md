# Phase 4 Execution Plan: Backend Preflight, Catalog, And Bundle Preservation

## Metadata

- Status: final phase execution plan; implementation not started
- Feature focus: External Artifact Interface
- PR title: `External Artifact Interface - Phase 4: Backend Preflight and Metadata Preservation`
- Branch: `codex/backend-preflight-catalog-bundles`
- Worktree: `/home/samcantrill/work/loom-worktrees/backend-preflight-catalog-bundles`
- Phase execution plan path:
  `docs/roadmap/stage-15/phases/backend-preflight-catalog-bundles.md`
- Full plan: `docs/roadmap/stage-15/implementation-plan.md`
- Source phase: Phase 4, `backend-preflight-catalog-bundles`
- Stack predecessor: none; Phase 3 is merged
- Base branch: `develop` at `96aaa0e9a2ac4c1dfc67d2d4eae2f677ac30a665`
- Target branch: `develop`
- Merge eligibility: root PR may merge to `develop` after implementation,
  validation, PR preparation, automated review, and GitHub merge checks.
- Workflow path: expanded path because this phase crosses diagnostics,
  public preflight models, run catalog metadata, and bundle metadata.
- Successor dependency notes: Phase 5 should branch from this phase branch only
  if this phase PR cannot merge; otherwise branch from updated `develop`.
- Plan quality gate: passed in the implementation plan; Phases 1-3 are merged
  and recorded.
- Draft pass: complete in this artifact.
- Refine pass: complete in this artifact; check IDs and Stage 12 non-schema
  boundary were tightened.
- Setup limitations: no product checks were run during planning.
- Blockers: none.

## Objective

Expose cheap Stage 15 artifact-backend preflight checks and add metadata
projection helpers/tests proving external, published, and location summaries
remain catalog/bundle metadata without payload movement or plugin discovery.

## Scope Contract

- Add a small preflight target model for configured artifact-backend checks.
- Extend `PreflightRequest` with supplied backend targets, an optional
  programmatic registry, and optional supplied handlers. These are explicit
  request inputs and do not discover or import plugins.
- Add stable artifact-backend check IDs:
  `artifact_backends.registry`, `artifact_backends.handlers`, and
  `artifact_backends.capabilities`, alongside existing
  `artifact_store.available`.
- Backend checks run cheap metadata operations only: normalize store kinds,
  inspect supplied registry/handlers, call `validate_store_ref`, redact store
  refs through handlers, and admit required capabilities.
- Missing handlers, missing registry entries, invalid store refs, and
  unsupported or unknown required capabilities fail closed.
- No network, credential, checksum, existence, lookup, publish, upload,
  download, or materialization probe is added.
- Add run metadata projection helpers for Stage 15 summary keys embedded in
  `ArtifactRef.metadata`; prove catalog summaries and bundle completed-run
  metadata preserve those plain summaries.
- Keep Stage 12 run-exchange schema changes out of scope.

## In-Scope Work

- Update diagnostics models and preflight execution for explicit artifact
  backend targets.
- Update stable preflight check ID contract tests.
- Add unit tests for no-target skips, no plugin discovery, missing handler
  failure, unsupported write failure, redacted handler details, and plugin
  metadata not satisfying backend readiness.
- Add small run metadata helper(s) and tests for external/published/location
  summary projection from `ArtifactRef.metadata`.
- Add catalog/bundle tests proving summaries survive in metadata-only records.

## Out-of-Scope Work

- Stage 12 exchange field/schema revision.
- Portable-run import/export behavior changes beyond metadata-preservation
  tests.
- Real backend adapters, SDKs, network probes, credential checks, payload
  transfer, materialization, retention cleanup, or authority mutation.
- Generic Stage 14 plugin load checks claiming backend availability.

## Design Impact

- User-visible preflight now distinguishes local artifact-store availability
  from artifact-backend registry, handler, and capability readiness.
- Diagnostics consume public store contracts only and keep backend readiness
  separate from plugin metadata/import success.
- Catalog/bundle summary preservation remains metadata-only and uses existing
  `ArtifactRef.metadata` rather than widening durable Stage 12 exchange
  schemas in this phase.

## Future Compatibility

Stage 16 can add opt-in materialization or payload-read checks under separate
IDs or policies. Phase 5 can decide whether run exchange needs explicit schema
fields after this phase proves current metadata projections are preserved.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reusing `plugins.load` as backend readiness | Stage 14 plugin import success is not run-readiness or configured handler availability. |
| Always creating or discovering plugin handlers | Violates explicit supplied-registry design and default no-plugin-import behavior. |
| Network/credential/checksum probes in default preflight | Contradicts cheap default checks and metadata-first semantics. |
| Stage 12 schema widening in this phase | Phase 5 owns exchange schema decisions after focused source recheck. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Backend preflight targets are supplied explicitly instead of auto-derived from authored config | Stage 15 has no authored backend config syntax yet, and auto-loading would blur readiness boundaries | A future stage adds first-class backend config declarations |
| Metadata projection helpers preserve summaries in `ArtifactRef.metadata` | Avoids premature exchange/catalog schema widening | Phase 5 proves extension/metadata placement is ambiguous |

## Reviewability

- Expected PR shape: diagnostics model/preflight changes, run metadata helper,
  targeted diagnostics/run tests, phase artifact, and PR body.
- Files and areas to inspect: stable check IDs, handler resolution, capability
  failure semantics, redaction details, and no plugin discovery on backend
  checks.
- Scope-control checks: no plugin auto-loading, no Stage 12 schema rewrite, no
  payload I/O, no real adapter imports.

## Test Plan

### Package Suite

- Status: focused update if public `loom.diagnostics` or `loom.runs` exports
  change.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/diagnostics`,
  `tests/unit/loom/runs`.
- Required assertions: backend preflight target normalization, no-target skip,
  missing handler failure, unsupported/unknown capability failure, handler
  redaction, plugin metadata separation, and metadata projection preservation.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_diagnostics_preflight_contract.py`,
  relevant run catalog/bundle contract tests if touched.
- Required assertions: stable check IDs include Stage 15 backend checks.

### Integration Suite

- Status: deferred for new focused coverage.
- Required assertions or deferral reason: no runner, service, or payload
  materialization behavior changes.

### E2E Suite

- Status: deferred.
- Required assertions or deferral reason: no CLI flow changes beyond existing
  preflight JSON model coverage.

### Opt-In Suites

- Status: deferred.
- Required assertions or deferral reason: no optional backend SDK or network
  suites.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/diagnostics tests/unit/loom/runs tests/contracts/test_diagnostics_preflight_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Budget Status

- Phase implementation refinement: unused.
- PR review: pending.
- Blocker-resolution budget: unused.
