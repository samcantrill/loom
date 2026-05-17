# Phase 1 Execution Plan: Event Grammar And Compatibility

## Metadata

- Status: draft phase execution plan
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
- Refine pass: pending for expanded path
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
- Existing tests or harness behavior: `tests/unit/loom/pipeline/test_events.py` locks schema-v1 record validation, `tests/unit/loom/pipeline/stores/test_local_runs.py` locks local event ordering and malformed log context, store contract and authority tests assert event append/read behavior, and offline evidence/import tests round-trip manifest events through `PipelineEventRecord.from_dict`.
- Import-boundary or dependency constraints: event record code must stay import-light and plain-data-compatible, relying only on lightweight serialization/timestamp helpers and avoiding concrete stores, execution, diagnostics, CLI, plugins, optional service SDKs, backend clients, or project code.

## In-Scope Work

- Update `loom.pipeline.events` or an adjacent import-light events package to expose the Stage 20 canonical record grammar.
- Introduce generic event resource and event or causal reference value objects, helpers, or plain-data contracts needed by `primary_resource`, `related_resources`, and `causal_predecessor`.
- Make new durable records serialize with `schema_version` 2, `event_id`, `run_uri`, `sequence`, `occurred_at`, `event_type`, `primary_resource`, `related_resources`, `payload`, and optional `causal_predecessor`.
- Preserve schema-v1 read/projection behavior for existing persisted records that use `timestamp` and `scope`, including deterministic compatibility `event_id` derivation from `run_uri` and `sequence`.
- Keep `event_type` as the canonical public persisted event-name field and avoid adding a separate persisted `event_name`.
- Update local and authority-compatible append/read paths only as needed to allocate durable sequence values, persist new event records, and continue reading schema-v1 data.
- Add or update package, unit, contract, integration, and offline consumer tests for the changed event grammar and compatibility behavior.
- Update immediate docs or docstrings only where needed to identify schema-v1 compatibility and events-as-audit-facts semantics.

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

## Scope Contract

New durable event records must use one canonical `PipelineEventRecord` family. The public persisted event-name field remains `event_type`; a persisted `event_name` field is out of scope. `sequence` remains a positive durable per-run append sequence allocated by the store and must not be repurposed for non-durable dispatch ordering. New records must have a stable `event_id`, `occurred_at`, a primary event resource, ordered related resources, a bounded plain-data payload, and an optional causal predecessor link.

Schema-v1 records remain valid inputs to `PipelineEventRecord.from_dict` or a named compatibility helper and must project without data loss for `run_uri`, `sequence`, `timestamp` to `occurred_at`, `scope` to resources, `event_type`, and `payload`. Malformed input should fail loudly with `PipelineEventError`; local log readers should continue wrapping failures with file and line context. The executor must not introduce concrete store, execution, plugin, diagnostics, CLI, optional SDK, or backend imports into event model modules.

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

## Implementation Steps

1. Define the Stage 20 event data contracts in the import-light event model layer, including resource refs, event references or causal links, schema-version constants, validation helpers, and explicit schema-v1 projection helpers.
2. Update `PipelineEventRecord` serialization and deserialization so new records emit schema-version 2 fields while schema-v1 inputs continue to project deterministically.
3. Adjust local and authority-compatible event append/read paths to create canonical durable records, preserve per-run ordering, and keep malformed local log errors tied to path and line context.
4. Update offline evidence/import and authority replay behavior as needed so old and new event records round trip through public helpers without log scraping or schema-specific duplication.
5. Add focused package, unit, contract, integration, and offline consumer tests for new field shape, schema-v1 projection, ordering, malformed records, and import boundaries.
6. Add minimal documentation or docstring notes for compatibility behavior and event-as-audit-fact semantics if the changed public record shape is otherwise unclear.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: exported store/event surfaces remain available as expected, and importing event records does not import plugins, CLI, concrete stores, execution, diagnostics, optional service SDKs, backend clients, or project code.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/test_events.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/test_offline_evidence.py`, and targeted authority/offline tests as changed
- Required assertions or deferral reason: schema-version 2 records round trip; schema-v1 payloads project correctly; invalid resources, timestamps, sequences, payloads, and unknown fields fail clearly; local event append/read preserves ordering and reports malformed records with file/line context; offline evidence emits compatible event records.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py`, `tests/contracts/test_authority_store_contract.py`
- Required assertions or deferral reason: public store protocols and authority-compatible event append/read behavior preserve durable sequence semantics, canonical record shape, and schema-v1 compatibility expectations across fake and concrete contract cases.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py`, `tests/integration/authority/test_offline_import_api.py`
- Required assertions or deferral reason: local `events.jsonl` remains append-only and ordered; authority offline import/replay can read manifest events through the compatibility projection; existing ordered audit-log examples still pass.

### E2E Suite

- Status: deferred
- Expected paths: `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason: no runtime dispatch behavior is intentionally changed in this phase. Existing e2e coverage may run through `make validate-pr`, but new phase-specific e2e assertions are deferred to Phase 3 runtime dispatch unless executor changes unexpectedly alter run-level event readback.

### Opt-In Suites

- Status: deferred
- Markers affected: no network, service, slow, or optional backend markers should be required
- Required assertions or deferral reason: this phase must remain local, deterministic, import-light, and dependency-light; service-specific, plugin, streaming, and strict-audit scenarios are future-phase or downstream-plugin scope.

## Risks

- Breaking existing schema-v1 `events.jsonl` or offline evidence manifests.
- Introducing import cycles by pulling store, execution, plugin, diagnostics, or CLI modules into event records.
- Hiding compatibility failures through overly permissive projection.
- Accidentally changing durable `sequence` semantics while adding event identity.
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

- Safe implementation slices: start with event model contracts and tests, then local/authority append-read adapters, then offline evidence/import compatibility, then docs/docstrings.
- Tests to run with each slice: run `tests/unit/loom/pipeline/test_events.py` after model changes; add local store and contract tests after append/read changes; add offline evidence/import tests after compatibility helper changes; run package import-boundary tests after any module split.
- Decisions the executor must not revisit: one canonical event family, `event_type` as the canonical persisted event-name field, schema-v1 read/projection compatibility, no eager log rewrite, no sink/dispatch/plugin/CLI scope, and no concrete store or runtime imports from event model modules.
- Conditions that require stopping for the manager: schema-v1 records cannot be projected without silent data loss; event models require concrete store/execution/plugin imports; a second event family appears necessary; durable sequence semantics conflict with event identity; or Stage 19 fact assumptions force a public record contract change.
- Expanded-path refinement notes: the refine pass should pressure-test public field names, compatibility helper names, resource/ref validation strictness, offline evidence/import impact, and whether any immediate docs update is required before implementation starts.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this commit
- Final phase execution plan: pending expanded-path refine pass
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none currently recorded
