# Phase 1 Execution Plan: Event Grammar And Compatibility

## Metadata

- Status: refined phase execution plan
- Feature focus: Runtime Events
- PR title: `Runtime Events - Phase 1: Event Grammar and Compatibility`
- Branch: `codex/event-grammar-compatibility`
- Worktree: `/home/samcantrill/work/loom-worktrees/event-grammar-compatibility`
- Phase execution plan path: `docs/roadmap/stage-20/phases/event-grammar-compatibility.md`
- Full plan: `docs/roadmap/stage-20/implementation-plan.md`
- Source phase: Phase 1, `event-grammar-compatibility`
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root PR; merge-eligible only after the PR targets `develop`, automated review passes, local validation passes, and GitHub CI passes
- Workflow path: expanded path
- Successor dependency notes: Phase 2 may stack on `codex/event-grammar-compatibility` only after this phase PR is opened or prepared, validated, and recorded by the manager
- Plan quality gate: verified passed in the implementation plan on 2026-05-17; no rerun performed
- Plan quality gate loop budget: consumed and passed before this phase plan; initial review, bounded refinement, and confirmation review are recorded in the implementation plan
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed by `loom_phase_planner` on 2026-05-17
- Setup limitations: remote sync succeeded from `origin/develop` after network-approved GitHub auth verification; sandboxed `gh auth status` reported a false invalid-token result without network access, and branch/worktree metadata creation required approved git metadata access
- Blockers: none

## Objective

Evolve Loom's canonical runtime event record grammar to the Stage 20 durable event contract while preserving schema-v1 local event and authority audit-event compatibility. This phase should leave existing event streams readable, avoid a parallel event family, and provide strict plain-data record helpers that later sink, dispatch, plugin, and diagnostic phases can reuse without importing runtime-heavy modules.

## Full-Plan Context

Stage 20 introduces audit-ready runtime events and observe-only event sinks over committed runtime facts. Phase 1 owns the event record grammar and compatibility layer first, so later phases can build sink registry contracts, observer facts, runtime dispatch, plugin loading, diagnostics, and documentation on one stable event family. This phase must not add sink registry or dispatch behavior, callback failure or observer-link persistence, plugin loading, broad CLI presentation, cleanup, service clients, streaming, strict audit mode, or Stage 19 runtime fact projection.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: the implementation plan records Phase 1 as pending with base and target `develop`, and all earlier Stage 20 phases are nonexistent
- Retarget/rebase plan after predecessor merge: not applicable for Phase 1; successor phases should rebase or retarget according to manager stack state after this PR lands or remains stacked
- Branch cleanup constraints: `codex/event-grammar-compatibility` can be deleted after merge only when no successor phase branch depends on it

## Source Phase Summary

- Goal: evolve the canonical event record family to the Stage 20 grammar while preserving schema-v1 local event compatibility.
- Required scope: implement the event field contract from the implementation plan, add generic event-resource and causal-link data contracts, update serialization/deserialization/projection helpers, and adjust local and authority-compatible append/read behavior where required.
- Required checkpoints: event API and import-boundary coverage; local, store contract, authority, offline evidence, and offline import compatibility coverage; useful malformed-record errors with record or file context.
- Acceptance criteria: new records round trip, old schema-v1 records read or project correctly without eager rewrite, per-run ordering remains deterministic, event resources and causal links are generic, and no service-specific fields or runtime-heavy imports enter core event records.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/events.py` currently defines schema-v1 `PipelineEvent`, `PipelineEventRecord`, `EventScope`, strict payload validation, and `PipelineEventRecord.from_dict`; `src/loom/pipeline/stores/local_runs.py` owns append-only `events.jsonl`; authority-compatible paths include `src/loom/pipeline/stores/sqlite_authority.py`, `src/loom/authority/_repository.py`, `src/loom/pipeline/stores/service_authority.py`, and `src/loom/pipeline/execution/authority_adapter.py`; offline consumers use `src/loom/pipeline/offline_evidence.py` and `src/loom/authority/offline_import.py`.
- Existing tests or harness behavior: `tests/unit/loom/pipeline/test_events.py` locks schema-v1 record validation, `tests/unit/loom/pipeline/stores/test_local_runs.py` locks local event ordering and malformed log context, store contract and authority tests assert event append/read behavior, package import-boundary tests currently import `loom.pipeline.events` with runtime-resource modules, and offline evidence/import tests round-trip manifest events through `PipelineEventRecord.from_dict`.
- Import-boundary or dependency constraints: event record code must stay import-light and plain-data-compatible, relying only on lightweight serialization/timestamp/id helpers from existing core modules or the standard library and avoiding concrete stores, execution, diagnostics, CLI, plugins, optional service SDKs, backend clients, or project code.

## In-Scope Work

- Update `loom.pipeline.events` or an adjacent import-light events package to expose the Stage 20 canonical record grammar.
- Introduce generic `EventResourceRef` and `EventReference` value objects, helpers, or plain-data contracts needed by `primary_resource`, `related_resources`, and `causal_predecessor`.
- Make new durable records serialize with `schema_version` 2, `event_id`, `run_uri`, `sequence`, `occurred_at`, `event_type`, `primary_resource`, `related_resources`, `payload`, and optional `causal_predecessor`.
- Preserve schema-v1 read/projection behavior for existing persisted records that use `timestamp` and `scope`, including deterministic compatibility `event_id` derivation through a named `compatibility_event_id(run_uri, sequence)` helper.
- Keep `event_type` as the canonical public persisted event-name field and avoid adding a separate persisted `event_name`.
- Update local and authority-compatible append/read paths only as needed to allocate durable sequence values, persist all new event-record fields, and continue reading schema-v1 data.
- Add or update package, unit, contract, integration, and offline consumer tests for the changed event grammar and compatibility behavior.
- Update immediate docs or docstrings only where needed to identify schema-v1 compatibility, the schema-version 2 field list, and events-as-audit-facts semantics; likely targets are `PipelineEventRecord` docstrings and `docs/features/reliability.md`'s event record shape, with broader user-facing docs left to Phase 4.

## Out-of-Scope Work

- Event sink registry, event sink dispatch, and `loom.pipeline.event_sinks`.
- Callback failure records, observer-link facts, and observer-link store/read facets.
- Runtime dispatch ordering, persistence-disabled non-durable envelopes, and Stage 19 reliability fact projection.
- Plugin entry point loading or `loom.plugins.event_sinks`.
- Broad CLI or diagnostic event presentation.
- Cleanup, deletion, retention, run-collection GC, strict audit mode, distributed streaming, service-specific sinks, and domain-specific tracking or metric semantics.

## Assumptions

- `schema_version` 2 is the Stage 20 durable event record version for new records.
- Existing schema-v1 `scope` values project to generic run or stage resources; stage-scope projection should include the parent run as a related resource.
- `PipelineEvent` may remain a lightweight append input, but persisted records and readback must expose the canonical durable record shape.
- Stage 19 fact names and record shapes can be projected later by Phase 3 adapters; Phase 1 only provides generic resource and causal-link capacity.
- Existing old logs are not rewritten during readback; compatibility projection is in-memory or explicit helper behavior.
- Authority storage may retain legacy columns for query/index compatibility, but new authority event rows must durably retain the full canonical event record shape before an append is acknowledged.

## Scope Contract

New durable event records must use one canonical `PipelineEventRecord` family. The public persisted event-name field remains `event_type`; a persisted `event_name` field is out of scope. `sequence` remains a positive durable per-run append sequence allocated by the store and must not be repurposed for non-durable dispatch ordering. New records must have a stable `event_id`, `occurred_at`, a primary event resource, ordered related resources, a bounded plain-data payload, and an optional causal predecessor link.

Canonical schema-version 2 persisted records must use exactly these top-level field names: `schema_version`, `event_id`, `run_uri`, `sequence`, `occurred_at`, `event_type`, `primary_resource`, `related_resources`, `payload`, and optional `causal_predecessor`. `timestamp`, `scope`, and `event_name` must not be written by `PipelineEventRecord.to_dict()` for schema-version 2 records. Backward-compatible read-only properties or adapter helpers may expose `timestamp` as an alias for `occurred_at` and `scope` as a projected run/stage scope when existing code needs a bridge, but those aliases are not part of the new persisted record grammar.

Compatibility helpers are part of the handoff contract:

- `PipelineEventRecord.from_dict(data)` dispatches by `schema_version`, returns a canonical `PipelineEventRecord`, accepts schema-version 1 and 2 inputs, and rejects unknown fields within the detected schema.
- `PipelineEventRecord.from_schema_v1_dict(data)` is the explicit schema-v1 projection helper used by `from_dict`, local readers, authority readers, offline import validation, and tests.
- `PipelineEventRecord.to_schema_v1_dict()` may exist only as an explicit compatibility projection for legacy adapter or fixture needs; ordinary new persistence must use `to_dict()` and schema-version 2.
- `compatibility_event_id(run_uri, sequence)` returns the deterministic schema-v1 event id used for projected legacy records. It must validate `run_uri` and positive `sequence`, be stable across processes, and must not depend on local file paths, authority row ids outside `sequence`, timestamps, or payload bytes.
- `PipelineEventRecord.to_event_reference()` returns the durable event-reference shape later phases will reuse for callback failures and causal links.

`EventResourceRef` must serialize as `{"kind": ..., "identifiers": ...}`. The `kind` is a non-empty lower-case identifier using the same dotted identifier style as event types. `identifiers` is a non-empty plain-data mapping with string keys. This phase should provide helpers for at least `EventResourceRef.run(run_uri)` and `EventResourceRef.stage(run_uri, stage_name)`. Run resources require `run_uri`; stage resources require `run_uri` and `stage_name`. For future core resource kinds such as artifact, submitted operation, retry, timeout, transaction, callback, provenance, or cleanup subjects, validation should stay strict on shape and plain-data compatibility without introducing a closed service-specific enum in Phase 1.

`EventReference` must serialize with `event_id`, `run_uri`, `event_type`, `occurred_at`, and `durability`. Durable references require `durability = "durable"` and a positive `sequence`; they must reject `dispatch_sequence`. Non-durable references may be accepted as a plain value shape for future Phase 3 use only if they require `durability = "non_durable"`, a positive `dispatch_sequence`, and no durable `sequence`; this phase must not add runtime non-durable dispatch. `causal_predecessor` accepts either an `EventResourceRef` shape or an `EventReference` shape and must reject ambiguous or unknown mappings.

Schema-v1 records remain valid inputs and must project without semantic data loss: `run_uri` remains `run_uri`; `sequence` remains the durable sequence; `timestamp` becomes `occurred_at`; `event_type` remains the canonical event-name field; `payload` is preserved unchanged; run `scope` projects to `EventResourceRef.run(run_uri)`; stage `scope` projects to `EventResourceRef.stage(run_uri, stage_name)` with the run resource in `related_resources`. Projected schema-v1 records have no causal predecessor unless a later documented compatibility helper can derive one without reading unstable payload conventions. Existing local logs and offline evidence files must not be rewritten merely because they were read.

Malformed input should fail loudly with `PipelineEventError` and include the record family and field name where possible. Local log readers must continue wrapping failures with file and line context. Offline import validation must surface invalid event records as `offline_import.event_invalid` rather than letting raw model exceptions escape. The executor must not introduce concrete store, execution, plugin, diagnostics, CLI, optional SDK, or backend imports into event model modules.

## Design Impact

- Maintainability: one canonical event family avoids duplicate record semantics while a compatibility projection isolates schema-v1 debt.
- Extensibility: generic event resources and causal references give later cleanup, sink, streaming, export/import, and provenance work stable nouns without service-specific fields.
- Domain neutrality: resource kinds and payload conventions must describe generic Loom runtime resources, not datasets, models, metrics, hosted telemetry, or notification targets.
- Source-tree boundaries: event grammar belongs in `loom.pipeline.events` or an adjacent import-light package; stores consume event records, and execution/plugin/diagnostic layers remain downstream.

## Future Compatibility

- Phase 2 should be able to reference event records from callback failure and observer-link facts without changing record identity fields.
- Phase 3 should be able to build durable and non-durable dispatch envelopes from the same event reference vocabulary without fabricating durable sequences.
- Phase 4 should be able to expose plugin and diagnostic inspection over public record helpers instead of log scraping.
- Stage 21 cleanup and future service plugins should consume resource refs and causal links without adding service-specific core fields.
- A future schema-v1 removal or archive window should be possible because compatibility behavior is explicit and tested.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a second Stage 20 runtime event type beside `PipelineEventRecord` | Creates parallel store, offline, sink, and diagnostic semantics that the implementation plan explicitly rejects |
| Rename the canonical public persisted event-name field to `event_name` | Breaks schema-v1 compatibility and conflicts with the reviewed event schema contract |
| Rewrite existing `events.jsonl` files eagerly to schema-version 2 | Adds unnecessary data-loss and migration risk; the phase only needs read/projection compatibility |
| Encode resources only inside free-form payloads | Forces future consumers to parse unstable payload conventions and weakens cleanup/sink/provenance reuse |
| Add sink or callback-failure fields directly to event records in this phase | Pulls Phase 2 and Phase 3 observer mechanics into the record grammar PR |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Schema-v1 projection remains in the event model | Existing local logs, offline evidence, and authority replay paths must remain readable | A documented compatibility window can remove or archive schema-v1 projection |
| Compatibility `scope` aliases may remain available at adapter boundaries | Current execution and tests still emit run/stage scoped events before later runtime refactors | Phase 3 dispatch migration or a public deprecation plan removes the need for scope-facing adapters |
| Exact Stage 19 resource references may be incomplete | Stage 19 reliability facts are not final in this phase and should not block generic grammar work | Phase 3 maps final Stage 19 committed facts into event resources |

## Reviewability

- Expected PR size and shape: moderate model and compatibility PR focused on event records, local/authority event persistence adapters, and targeted tests; no runtime sink or plugin behavior.
- Files and areas to inspect: `src/loom/pipeline/events.py` or adjacent event package, local `events.jsonl` append/read paths, authority audit-event append/read adapters, offline evidence/import event handling, package import-boundary tests, event unit tests, store contract tests, local store integration tests, and any immediate feature-doc or docstring update.
- Scope-control checks: no `loom.pipeline.event_sinks`, no plugin loading, no service SDK dependencies, no CLI event-management surface, no eager local log migration, and no broad runtime dispatch rewiring.
- Persistence review checks: local and authority append paths must persist every schema-version 2 field or stop with a blocker; authority readers may project legacy rows, but they must not acknowledge a new record after dropping `event_id`, resources, or `causal_predecessor`.

## Implementation Steps

1. Define the Stage 20 event data contracts in the import-light event model layer, including `EventResourceRef`, `EventReference`, schema-version constants, validation helpers, and the named schema-v1 projection helpers.
2. Update `PipelineEventRecord` serialization and deserialization so new records emit schema-version 2 fields while schema-v1 inputs project deterministically through `PipelineEventRecord.from_schema_v1_dict`.
3. Adjust local `events.jsonl` append/read paths to create canonical durable records after the final store sequence is known, preserve per-run ordering across mixed v1/v2 logs, and keep malformed local log errors tied to path and line context.
4. Adjust authority-compatible append/read paths so new rows retain the full canonical event record shape while legacy rows still project through the same schema-v1 helper; do not drop v2-only fields into legacy-only columns.
5. Update offline evidence/import and authority replay behavior so new manifests emit schema-version 2 records, old manifests validate through compatibility projection, replay events preserve canonical projected event identity, and source manifests are not rewritten.
6. Add focused package, unit, contract, integration, and offline consumer tests for new field shape, helper semantics, schema-v1 projection, ordering, malformed records, and import boundaries.
7. Add minimal documentation or docstring notes for compatibility behavior, event-as-audit-fact semantics, and the schema-version 2 field list if the changed public record shape is otherwise unclear.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: exported store/event surfaces remain available as expected; any new public `EventResourceRef`, `EventReference`, schema constants, or compatibility helpers are intentionally exported; and importing event records or an adjacent event package does not import plugins, CLI, concrete stores, execution, diagnostics, optional service SDKs, backend clients, or project code.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/test_events.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/test_offline_evidence.py`, and targeted authority/offline tests as changed
- Required assertions or deferral reason: schema-version 2 records round trip with the exact public fields; `to_dict()` omits `timestamp`, `scope`, and `event_name`; schema-v1 payloads project correctly through `from_dict` and `from_schema_v1_dict`; `compatibility_event_id` is deterministic; `EventResourceRef` and `EventReference` reject malformed resources, references, timestamps, sequences, payloads, unknown fields, and ambiguous causal predecessors; local event append/read preserves ordering and reports malformed records with file/line context; offline evidence emits compatible event records.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py`, `tests/contracts/test_authority_store_contract.py`
- Required assertions or deferral reason: public store protocols and authority-compatible event append/read behavior preserve durable sequence semantics, canonical schema-version 2 record shape, full v2 field persistence, and schema-v1 compatibility expectations across fake and concrete contract cases.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py`, `tests/integration/authority/test_offline_import_api.py`
- Required assertions or deferral reason: local `events.jsonl` remains append-only and ordered across new v2 lines and old v1 fixture lines; authority offline import/replay can read manifest events through the compatibility projection; replay audit events preserve canonical projected event identity; existing ordered audit-log examples still pass.

### E2E Suite

- Status: deferred
- Expected paths: `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason: no sink dispatch or runtime ordering behavior is intentionally changed in this phase. Existing e2e coverage may run through `make validate-pr`, but new phase-specific e2e assertions are deferred to Phase 3 runtime dispatch unless executor changes unexpectedly alter run-level event readback.

### Opt-In Suites

- Status: deferred
- Markers affected: no network, service, slow, or optional backend markers should be required
- Required assertions or deferral reason: this phase must remain local, deterministic, import-light, and dependency-light; service-specific, plugin, streaming, and strict-audit scenarios are future-phase or downstream-plugin scope.

## Risks

- Breaking existing schema-v1 `events.jsonl` or offline evidence manifests.
- Introducing import cycles by pulling store, execution, plugin, diagnostics, or CLI modules into event records.
- Hiding compatibility failures through overly permissive projection.
- Accidentally changing durable `sequence` semantics while adding event identity.
- Dropping schema-version 2 fields in authority storage by continuing to persist only the legacy `timestamp` and `scope_json` column shape.
- Overfitting resource kinds to unfinished Stage 19 reliability facts or service-specific sink needs.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/test_events.py
uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_local_stores.py
uv run pytest tests/unit/loom/pipeline/test_offline_evidence.py tests/integration/authority/test_offline_import_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with event model contracts and tests, then local append/read adapters, then authority-compatible persistence/read adapters, then offline evidence/import compatibility, then minimal docs/docstrings.
- Tests to run with each slice: run `tests/unit/loom/pipeline/test_events.py` after model changes; run `tests/unit/loom/pipeline/stores/test_local_runs.py` after local append/read changes; run store contract and authority tests after authority persistence changes; run offline evidence/import tests after compatibility helper changes; run package import-boundary tests after any module split or new public export.
- Decisions the executor must not revisit: one canonical event family; exact v2 public field names; `event_type` as the canonical persisted event-name field; `PipelineEventRecord.from_dict`, `PipelineEventRecord.from_schema_v1_dict`, `PipelineEventRecord.to_schema_v1_dict`, `PipelineEventRecord.to_event_reference`, `EventResourceRef`, `EventReference`, and `compatibility_event_id` as the planned helper names unless an implementation blocker is recorded; schema-v1 read/projection compatibility; no eager log rewrite; no sink/dispatch/plugin/CLI scope; and no concrete store or runtime imports from event model modules.
- Conditions that require stopping for the manager: schema-v1 records cannot be projected without silent data loss; event models require concrete store/execution/plugin imports; a second event family appears necessary; durable sequence semantics conflict with event identity; authority storage cannot retain all v2 fields without a schema/migration decision outside this phase; or Stage 19 fact assumptions force a public record contract change.
- Expanded-path refinement notes: completed. The refined plan locks public field names, compatibility helper names, resource/reference validation strictness, offline evidence/import behavior, authority persistence expectations, import-boundary obligations, and immediate docs/docstring needs.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this commit
- Final phase execution plan: completed by expanded-path refine pass on 2026-05-17
- Implementation summary: implemented schema-version 2 `PipelineEventRecord`
  grammar with `EventResourceRef`, `EventReference`,
  `compatibility_event_id`, schema-v1 projection helpers, v2 durable
  references, local `events.jsonl` v2 writes, authority `event_json` retention
  for canonical records, offline evidence/import compatibility, focused tests,
  and minimal reliability docs.
- Implementation validation:
  - `uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/test_events.py` passed, 98 tests.
  - `uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_local_stores.py` passed, 67 tests.
  - `uv run pytest tests/unit/loom/pipeline/test_offline_evidence.py tests/integration/authority/test_offline_import_api.py` passed, 5 tests.
  - Additional authority/offline confidence run: `uv run pytest tests/unit/loom/pipeline/test_offline_evidence.py tests/integration/authority/test_offline_import_api.py tests/unit/loom/authority/test_offline_import.py tests/integration/authority/test_repository_run_lifecycle.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py` passed, 26 tests.
  - `make validate-pr` passed: Ruff, Pyright, default harness, config-extra harness, and build.
- Refinement summary:
  - Pass type: implementation refinement.
  - Validation output reviewed: executor-reported targeted package/unit/contract/integration/offline runs and `make validate-pr` pass, then refinement reruns listed below.
  - Blocking issues caused by this phase: `PipelineEventRecord` treated explicit falsy constructor inputs for `payload` and `event_id` as missing instead of malformed; private authority repositories opened against the legacy global-primary-key `audit_events` table could allocate duplicate sequence keys when Stage 20 per-run event sequences were appended for a second run.
  - Issues confirmed out of scope: no sink registry, runtime dispatch, plugin loading, callback failure records, observer links, CLI presentation, or future Phase 2+ behavior was changed.
  - Fixes made:
    | Issue | Change | Evidence |
    | --- | --- | --- |
    | Falsy event-record constructor values bypassed strict validation | Distinguished `None` defaults from invalid falsy `payload` and `event_id` values and added unit regressions | `uv run pytest tests/unit/loom/pipeline/test_events.py tests/integration/authority/test_repository_run_lifecycle.py` passed, 37 tests |
    | Legacy private authority `audit_events` primary key conflicted with per-run sequence allocation | Migrated the private repository table to the Stage 20 `(run_uri, sequence)` primary key while preserving legacy rows and added a file-backed regression | `uv run pytest tests/unit/loom/authority/test_repository_run_lifecycle.py tests/unit/loom/authority/test_offline_import.py tests/integration/authority/test_repository_run_lifecycle.py` passed, 15 tests |
  - Tests or validation re-run:
    - `uv run pytest tests/unit/loom/pipeline/test_events.py tests/integration/authority/test_repository_run_lifecycle.py` passed, 37 tests.
    - `uv run pytest tests/unit/loom/authority/test_repository_run_lifecycle.py tests/unit/loom/authority/test_offline_import.py tests/integration/authority/test_repository_run_lifecycle.py` passed, 15 tests.
    - `uv run ruff check src/loom/pipeline/events.py src/loom/authority/_repository.py tests/unit/loom/pipeline/test_events.py tests/integration/authority/test_repository_run_lifecycle.py` passed.
    - `uv run pyright src/loom/pipeline/events.py src/loom/authority/_repository.py tests/unit/loom/pipeline/test_events.py tests/integration/authority/test_repository_run_lifecycle.py` passed.
  - PR preparation handoff: completion notes updated, phase implementation refinement budget marked `used`, blocker-resolution budget unchanged at `0/3 used`, and final PR preparation should still run `make validate-pr` and `make test-summary`.
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none currently recorded
