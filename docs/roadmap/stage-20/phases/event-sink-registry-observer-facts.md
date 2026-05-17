# Phase 2 Execution Plan: Sink Registry And Observer Facts

## Metadata

- Status: final phase execution plan; scope-complete for implementation
- Feature focus: Runtime Events
- PR title: `Runtime Events - Phase 2: Sink Registry and Observer Facts`
- Branch: `codex/event-sink-registry-observer-facts`
- Worktree: `/home/samcantrill/work/loom-worktrees/event-sink-registry-observer-facts`
- Phase execution plan path: `docs/roadmap/stage-20/phases/event-sink-registry-observer-facts.md`
- Full plan: `docs/roadmap/stage-20/implementation-plan.md`
- Source phase: Phase 2, `event-sink-registry-observer-facts`
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root PR; merge-eligible only after the PR targets `develop`, automated review passes, local validation passes, GitHub CI passes, and the phase remains scoped to Phase 2
- Workflow path: expanded path
- Successor dependency notes: Phase 3 may stack on this branch only after the Phase 2 PR is opened or prepared, validated, and recorded by the manager as a valid continuation base
- Plan quality gate: verified passed in the implementation plan on 2026-05-17; no quality-gate rerun performed
- Plan quality gate loop budget: consumed and passed before this phase plan; the implementation plan records one review, one bounded refinement, and one confirmation review with no remaining findings
- Draft pass: completed by `loom_phase_planner` on 2026-05-17
- Refine pass: completed by `loom_phase_planner` on 2026-05-17; manager boundary findings incorporated
- Setup limitations: existing branch/worktree supplied by the manager was reused after verification; it is checked out as `codex/event-sink-registry-observer-facts` at `f17fe6955c26f55d4071ef49037e787121aaee69`, already realigned to current `develop`. No remote synchronization, branch recreation, broad validation, product-code implementation, or PR work was performed in the draft or refine pass.
- Blockers: none; this artifact is scope-complete for Phase 2 implementation

## Objective

Add Loom's import-light event sink contract, deterministic instance-local sink registry, dispatch result model, callback failure records, observer-link records, and narrow observer-fact store/read facets. The phase should make observers explicit and inspectable without letting sinks mutate core run state or making plugin loading/runtime dispatch part of this PR.

## Full-Plan Context

Stage 20 first stabilized the canonical event grammar in merged Phase 1. Phase 2 builds the observer contract and durable observer facts on top of that event identity model so Phase 3 can dispatch from committed facts and persist callback failures through narrow store facets. Phase 4 will load plugin entry points, diagnostics, CLI/read-model presentation, and broader docs. This phase must keep plugin loading, runtime dispatch wiring, persistence-disabled non-durable dispatch behavior, service-specific sinks, cleanup, strict audit mode, and event-driven runtime mutation out of scope.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 is merged into `develop`; the manager supplied no stack predecessor and confirmed this worktree/branch was realigned to current `develop` at `f17fe69`
- Retarget/rebase plan after predecessor merge: not applicable unless a later manager decision opens Phase 3 as a successor before this phase merges
- Branch cleanup constraints: `codex/event-sink-registry-observer-facts` can be deleted after merge only when no successor phase branch depends on it

## Source Phase Summary

- Goal: add an import-light event sink contract, instance-local registry, dispatch result model, callback failure record, and narrow observer-link writeback surface without runtime plugin loading.
- Required scope: define `EventSink`, `EventSinkRegistry`, `EventSinkContext`, dispatch result, callback failure record, observer-link record, narrow structural context/recorder protocols, and store/read facets for callback failure and observer-link facts.
- Required checkpoints: deterministic registry behavior, no store imports from `loom.pipeline.event_sinks`, plain-data-compatible observer fact serialization/readback, package/import tests, sink unit tests, store contract tests, and local integration tests.
- Acceptance criteria: explicit registries can register and dispatch fake sinks deterministically; duplicate sink names are handled deterministically; callback failures and observer links serialize and read back; sink contexts expose no broad mutation handles; stores persist observer facts but do not execute sinks.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: current `develop` includes Phase 1's schema-version 2 `PipelineEventRecord`, `EventResourceRef`, `EventReference`, and durable `to_event_reference()` helpers in `src/loom/pipeline/events.py`; `src/loom/pipeline/stores/run_store.py` exposes `RunEventStore`; local event persistence lives in `src/loom/pipeline/stores/local_runs.py`; likely store/read touch points are `src/loom/pipeline/stores/run_store.py`, `src/loom/pipeline/stores/local_runs.py`, `src/loom/pipeline/stores/sqlite_authority.py`, `src/loom/pipeline/stores/service_authority.py`, `src/loom/pipeline/stores/read_models.py`, and authority-compatible repository/adapters only where those store paths require them.
- Existing tests or harness behavior: `tests/unit/loom/pipeline/test_events.py` locks event identity and reference semantics; `tests/package/test_import_boundaries.py` checks import boundaries; `tests/package/test_pipeline_store_api.py` checks store API exports; `tests/contracts/test_store_contract.py` and `tests/contracts/test_authority_store_contract.py` exercise store protocols; local observer-fact integration coverage belongs in `tests/integration/pipeline/test_local_stores.py` or an adjacent local-store integration test.
- Import-boundary or dependency constraints: `loom.pipeline.event_sinks` must be as import-light as the event model layer and must not import `loom.pipeline.stores`, concrete stores, execution, diagnostics, CLI, plugin discovery, optional service SDKs, backend clients, or project code. Store modules may import observer record types from `loom.pipeline.event_sinks`; sink contracts must use narrow structural protocols rather than broad store protocols.

## In-Scope Work

- Add a new public import target at `loom.pipeline.event_sinks` as a module or package, keeping the direct module import lightweight.
- Define the event sink callback contract and context contract over Phase 1 event identity records and references.
- Define an instance-local `EventSinkRegistry` with deterministic registration order and duplicate-name rejection.
- Define dispatch result and per-sink result/failure data that can represent successful callbacks and best-effort callback exceptions without changing run correctness.
- Define plain-data-compatible `EventSinkFailureRecord` values that reference the triggering durable or non-durable event identity through `EventReference`.
- Define plain-data-compatible `EventObserverLinkRecord` values for narrow external references written by trusted sinks.
- Add narrow structural protocols for observer-link recording and callback-failure recording; these protocols must not expose full `RunStore`, status, artifact, retry, transaction, or metadata mutation APIs.
- Add store/read facets for callback failure and observer-link facts, including typed append/read methods, deterministic append-order readback, local sidecar JSONL persistence, and authority/fake-store contract support as needed.
- Keep local observer facts in separate observer-fact sidecar JSONL files rather than writing them as ordinary `events.jsonl` event records.
- Add package, unit, contract, and integration tests for the new sink API, registry behavior, mutation boundary, observer fact serialization, and observer fact persistence.
- Add concise docstrings or nearby feature-doc updates where needed to state observe-only guarantees, duplicate behavior, best-effort failure policy, and writeback limits.

## Out-of-Scope Work

- Runtime append/project/dispatch wiring in `loom.pipeline.execution`.
- Plugin entry point loading, ambient plugin discovery, or a global sink registry.
- Service-specific sinks or bundled clients for telemetry, webhooks, notifications, tracking services, OpenTelemetry, or streaming systems.
- Persistence-disabled non-durable runtime dispatch behavior beyond validating inert record/reference shapes needed by the public contract.
- Persisting callback failures or observer links as ordinary `PipelineEventRecord` values, `audit_events` rows, or `events.jsonl` lines.
- Strict audit mode, distributed streaming, cleanup, deletion, retention, run-collection GC, or retry/resource policy changes.
- Event-driven mutation of plans, configs, artifacts, stage outputs, statuses, retry decisions, transactions, submitted operations, core store records, or broad run metadata.
- CLI or diagnostics presentation except minimal docs/import-boundary changes required by the new module surface.

## Assumptions

- Phase 1 event grammar is merged into `develop` and provides `EventReference` for durable and future non-durable event identity references.
- Sink registry dispatch in this phase may be exercised with fake durable event records; runtime emission, persistence defaults, and non-durable dispatch warnings are Phase 3 scope.
- Duplicate sink names should fail by default instead of silently overwriting an existing registration. Future plugin loading can surface duplicate entry point names as registration errors.
- Observer links are generic external-reference facts, not service-specific telemetry records.
- Callback failures are event-adjacent observer facts. They are not ordinary sink-dispatched runtime events in this phase.
- Stores may import `EventSinkFailureRecord` and `EventObserverLinkRecord` from `loom.pipeline.event_sinks`; `loom.pipeline.event_sinks` must not import stores to discover or type those facets.
- If `develop` changes event identity fields before Phase 2 implementation starts, the expanded-path refine pass must update this plan before implementation starts.

## Scope Contract

`loom.pipeline.event_sinks` is the public contract surface for sink mechanics in this phase. It must remain import-light and independent of store implementations. Direct imports of `loom.pipeline.event_sinks` may import `loom.pipeline.events`, serialization helpers, timestamps, dataclasses, standard typing, and standard library helpers only when needed; they must not import `loom.pipeline.stores`, execution, plugins, diagnostics, CLI, optional service SDKs, backend clients, or project code. The allowed direction is store modules importing observer record types from `event_sinks`, not `event_sinks` importing stores or broad store protocols.

`EventSink` is an observe-only callback contract. A sink may observe the triggering event identity/record and may write only observer-link facts through a narrow context protocol. It must not receive a full store, runner, execution plan, mutable stage state, artifact writer, status mutator, retry mutator, transaction mutator, submitted-operation mutator, or arbitrary run metadata writer. Registry dispatch must continue to later sinks after a sink failure by default and report failures through dispatch results and callback failure records.

`EventSinkRegistry` is instance-local. It must not use module-level mutable global registration. Registrations are keyed by non-empty deterministic sink names. Names should use the same lower-case dotted or identifier-like vocabulary already used for event/plugin keys unless the implementation discovers a stronger existing local validator. Registration order defines dispatch order. Registering a duplicate name without an explicit future override API must raise a registry error; silent replacement is out of scope.

`EventSinkFailureRecord` is the callback failure fact. It must include a schema version, sink name, failure type, failure message, optional plain-data detail, failure timestamp, run URI, and an `EventReference` for the triggering event identity. Failure detail must avoid raw callback objects, credentials, large blobs, or backend-specific exception objects. Failure records may include a generated failure id or store-assigned observer-fact identity, but they must not reuse durable event sequence numbers or recursively become ordinary runtime events.

`EventObserverLinkRecord` is the observer-link fact. It must include a schema version, sink name, run URI, triggering `EventReference`, recorded timestamp, and a generic external reference with a non-empty kind and plain-data identifiers. Optional metadata must remain bounded plain data. The schema must not include service-specific top-level fields such as tracking server URLs, webhook payloads, model IDs, metric names, credentials, or notification channels. Richer observer summaries are future work.

Store/read facets must persist and read callback failure and observer-link facts as append-only event-adjacent facts. The public store protocol surface for this phase is `RunEventSinkFailureStore` with `append_event_sink_failure` and `read_event_sink_failures`, plus `RunEventObserverLinkStore` with `append_event_observer_link` and `read_event_observer_links`. Append methods accept typed observer records; read methods return typed record values in deterministic append order. Stores own persistence, append ordering, and run ownership validation where the existing store can enforce it; sinks and registries do not execute store writes directly except through narrow structural context protocols supplied by runtime setup.

Local stores must persist observer facts in separate observer-fact sidecar JSONL files under the run directory, expected as `event_sink_failures.jsonl` and `event_observer_links.jsonl` unless the implementation finds a stronger existing local naming convention. They must not mix callback failures or observer links into ordinary `events.jsonl`, and ordinary `read_events` must continue to return only `PipelineEventRecord` audit events. Authority-compatible stores should use distinct tables or fields for observer facts rather than `audit_events` rows. Fake and contract stores must validate run ownership where possible and reject plain-data or event-reference shape errors consistently with existing store error behavior.

## Design Impact

- Maintainability: separating `event_sinks` from stores and execution keeps observer mechanics testable with fakes and prevents callback behavior from becoming a hidden execution authority.
- Extensibility: a small registry, result model, failure record, and observer-link record can be reused by Phase 3 runtime dispatch, Phase 4 plugin loading, future strict audit mode, and downstream service adapters.
- Domain neutrality: observer links use generic external references and plain-data metadata instead of model, metric, dataset, notification, or hosted-telemetry nouns.
- Source-tree boundaries: event identity remains in `loom.pipeline.events`; observer contracts live in `loom.pipeline.event_sinks`; persistence facets belong under `loom.pipeline.stores`; plugin discovery and diagnostics stay downstream.

## Future Compatibility

- Phase 3 can dispatch committed `PipelineEventRecord` values through the registry and record callback failures through the store facets without changing the sink protocol.
- Phase 3 can add non-durable dispatch envelopes or helpers using the existing `EventReference` semantics without fabricating durable store sequences.
- Phase 4 can load `loom.event_sinks` entry points into an explicit registry and report duplicate registration failures without changing core event semantics.
- Future strict audit mode can treat callback failures or persistence-disabled dispatch differently because failure facts are explicit and not swallowed.
- Stage 21 cleanup and future service integrations can use observer links for traceability without adding cleanup, deletion, or service-specific fields to Stage 20 core records.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Use a process-global event sink registry | Creates ambient behavior, complicates tests, and conflicts with explicit trusted runtime setup |
| Let `event_sinks` import `loom.pipeline.stores` or concrete stores | Reintroduces store/sink cycles and violates the reviewed import-light boundary |
| Pass full `RunStore` or runner objects to sinks | Allows observers to mutate execution correctness surfaces instead of remaining observe-only |
| Treat callback failures as ordinary sink-dispatched events | Risks recursive callback loops and failure amplification |
| Silently overwrite duplicate sink names | Makes plugin and programmatic registration order hard to audit |
| Add service-specific observer-link fields in core records | Breaks Loom's domain-neutral contract and pulls plugin adapter semantics into core runtime |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Observer-link schema starts intentionally narrow | Prevents broad metadata mutation and service-specific core fields while giving integrations a traceability hook | Multiple downstream integrations need richer observer summaries that cannot fit generic external references |
| Callback failures are event-adjacent facts, not recursively dispatched events | Avoids callback loops and keeps observers outside run correctness | A future strict audit mode or monitoring design needs callback-failure events with loop prevention |
| Plugin loading remains deferred | The registry contract must stabilize before `loom.event_sinks` entry points are loaded | Phase 4 implements explicit plugin loading over this registry |

## Reviewability

- Expected PR size and shape: moderate public-contract and store-facet PR with one import-light sink module/package, observer record types, narrow store protocol/readback additions, local/fake/authority persistence support where required, and focused tests.
- Files and areas to inspect: `src/loom/pipeline/event_sinks.py` or `src/loom/pipeline/event_sinks/`, `src/loom/pipeline/stores/run_store.py`, `src/loom/pipeline/stores/__init__.py`, `src/loom/pipeline/stores/local_runs.py`, `src/loom/pipeline/stores/sqlite_authority.py`, `src/loom/pipeline/stores/service_authority.py`, `src/loom/pipeline/stores/read_models.py`, authority-compatible repository/adapters only as needed, `tests/unit/loom/pipeline/test_event_sinks.py`, package import/API tests, store contract tests, authority-store contract tests, and local store integration tests.
- Scope-control checks: no runtime dispatch wiring, no plugin loader, no global registry, no sink access to full stores or runtime mutators, no service SDK dependencies, no ordinary runtime events for callback failures or observer links, no observer facts in `events.jsonl`, and no `events.jsonl` rewrite or schema-v1 event grammar changes.

## Implementation Steps

1. Add the import-light `loom.pipeline.event_sinks` public surface with sink/context protocols, registry errors, deterministic instance-local registry behavior, dispatch result records, `EventSinkFailureRecord`, and `EventObserverLinkRecord`.
2. Add strict plain-data serialization/deserialization, event-reference validation, bounded detail/metadata handling, and malformed-shape tests for the observer records.
3. Add `RunEventSinkFailureStore` and `RunEventObserverLinkStore` facets/exports, then implement them in local, fake, and authority-compatible stores as append-only typed facts with deterministic append-order readback and run ownership validation where enforceable.
4. Add local sidecar JSONL persistence for observer facts, keeping `event_sink_failures.jsonl` and `event_observer_links.jsonl` separate from ordinary `events.jsonl` reads/writes.
5. Add registry and mutation-boundary tests using fake sinks and fake structural contexts; assert duplicate rejection, dispatch order, best-effort failure collection, and absence of broad mutation handles.
6. Add package/import-boundary tests and minimal docs/docstrings for observe-only guarantees, writeback limits, duplicate handling, and best-effort callback failure semantics.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: add a subprocess import-boundary test that imports `loom.pipeline.event_sinks` directly and fails if it imports concrete stores (`loom.pipeline.stores`, `local_runs`, `sqlite_authority`, `service_authority`), execution, plugins, diagnostics, CLI, optional SDKs/backend clients (`mlflow`, `wandb`, `boto3`, `botocore`, `google.cloud`, `azure`, `requests`, `httpx`, or similar), or project code. Package API tests must intentionally expose `EventSink`, `EventSinkRegistry`, `EventSinkContext`, dispatch result types, `EventSinkFailureRecord`, `EventObserverLinkRecord`, `RunEventSinkFailureStore`, and `RunEventObserverLinkStore` through the chosen public module/store exports where repository convention requires.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/test_event_sinks.py`, plus `tests/unit/loom/pipeline/stores/test_local_runs.py` or an adjacent local observer-fact test module if local persistence helpers need direct unit coverage
- Required assertions or deferral reason: registry names validate; duplicate registration raises; dispatch order follows registration order; sink failures are captured without stopping later sinks; `EventSinkFailureRecord` includes sink name, event reference, timestamp, failure type/message, optional plain-data detail, and any store-assigned observer-fact identity without reusing event sequence semantics; `EventObserverLinkRecord` validates generic external references and rejects service-specific or non-plain-data shapes; fake contexts expose only narrow observer-link/failure recorder methods.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py`, `tests/contracts/test_authority_store_contract.py`
- Required assertions or deferral reason: fake and concrete contract stores satisfy `RunEventSinkFailureStore` and `RunEventObserverLinkStore`; callback failure and observer-link append/read methods validate run ownership where existing stores can enforce it and reject invalid plain-data/event-reference shapes; readback returns typed records in deterministic append order; observer facts do not satisfy or mutate lifecycle, artifact, status, retry, transaction, submitted-operation, or runtime metadata protocols.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py` and authority/local integration paths touched by the store implementation
- Required assertions or deferral reason: local run directories persist callback failure and observer-link facts durably to separate observer-fact sidecar JSONL files, read them after a fresh store instance is created, preserve append order, keep ordinary event reads separate from observer-fact reads, and prove `events.jsonl` contains only `PipelineEventRecord` audit events.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase
- Required assertions or deferral reason: no runtime dispatch, CLI, diagnostics, plugin loading, or full pipeline execution behavior changes in Phase 2. Phase 3 and Phase 4 own end-to-end dispatch and presentation coverage.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: this phase introduces no optional service SDKs, remote services, slow external systems, or opt-in backend markers. If authority adapter changes touch existing opt-in suites, they should be run only when those paths are directly modified and then recorded in PR evidence.

## Risks

- Store/sink import cycles if `event_sinks` imports concrete store protocols directly.
- Broad context power if sinks receive a full store, runner, or mutable runtime object.
- Ambiguous duplicate sink behavior if registration does not reject conflicts deterministically.
- Observer-link schema creep into service-specific telemetry or tracking fields.
- Callback failure recursion if failures are persisted as ordinary sink-dispatched runtime events.
- Stale branch state if `develop` changes event identity or store protocol shape before this phase is implemented.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/test_event_sinks.py
uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/unit/loom/pipeline/stores tests/integration/pipeline/test_local_stores.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: define the import-light sink API first; add record serialization next; add store facets and local/fake/authority persistence after record tests pass; finish with import/package docs and integration coverage.
- Tests to run with each slice: run `tests/unit/loom/pipeline/test_event_sinks.py` after registry/record slices, package import tests after public surface changes, and store contract/local integration tests after persistence facets are added.
- Decisions the executor must not revisit: keep registry instance-local; reject duplicate names deterministically; do not import stores from `event_sinks`; do not pass broad mutation handles to sinks; do not implement plugin loading or runtime dispatch in this phase.
- Conditions that require stopping for the manager: Phase 1 event identity fields are unavailable or materially changed on `develop`; callback failure or observer-link persistence requires arbitrary run metadata mutation; deterministic registry behavior requires a global registry; `event_sinks` cannot stay import-light; or store facets cannot persist/read observer facts without treating them as ordinary runtime events.
- Expanded-path refinement notes: the refine pass should verify final public names for observer records/store facets, confirm duplicate-name behavior remains reviewable for Phase 4 plugin loading, and adjust the plan if current `develop` changes event identity or store protocol assumptions.

## Refinement And Review Budget Status

- Phase implementation refinement: used by manager local refinement after
  `make validate-pr` Pyright found the HTTP authority adapter missing the new
  observer-fact methods and unit test callables using overly narrow types
- PR review: used by manager local review on 2026-05-17; no blocking findings
  found, scope confirmed limited to Phase 2 sink contracts, observer fact
  stores, tests, and docs
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-17
- Final phase execution plan: completed by expanded-path refine pass on
  2026-05-17; manager boundary findings incorporated
- Implementation summary: import-light `loom.pipeline.event_sinks` contract,
  instance-local `EventSinkRegistry`, dispatch result records,
  `EventSinkFailureRecord`, `EventObserverLinkRecord`, narrow observer
  recorder/context protocols, local JSONL observer-fact sidecars, SQLite and
  service authority observer-fact persistence, authority-adapter forwarding,
  fake authority support, package/import tests, unit tests, store contract
  tests, authority contract tests, local store integration coverage, and docs
  updates are implemented.
- Implementation validation: targeted Phase 2 package/event-sink suite passed
  with 72 tests; targeted store contract/local integration suite passed with
  225 tests; `make validate-pr` passed Ruff, Pyright, default harness,
  config-extra harness, and build; `make test-summary` passed with package 105
  passed/1 skipped, unit 1350 passed/7 skipped/1 deselected, contract 263
  passed/2 skipped, integration 165 passed/8 skipped/13 deselected, e2e 44
  passed/2 deselected, and config-extra 447 passed/3 skipped/1936 deselected.
- Refinement summary: added observer-fact methods to the HTTP
  `AuthorityClientBackedPerRunAuthorityStore` fallback surface and tightened
  event-sink unit test type signatures after Pyright validation.
- Blocker-resolution summary: none needed
- PR preparation: PR body artifact completed at
  `docs/roadmap/stage-20/phases/event-sink-registry-observer-facts-pr-body.md`;
  PR [#188](https://github.com/samcantrill/loom/pull/188) opened against
  `develop`; verification confirmed base `develop`, head
  `codex/event-sink-registry-observer-facts`, state `OPEN`, and GitHub CI
  `checks` success.
- Stack maintenance: root PR; Phase 3 successor branch
  `codex/runtime-event-dispatch` was created from this branch before merge, so
  the branch must be kept during Phase 2 merge and deleted only after Phase 3 is
  rebased or replayed onto `develop`.
- Remaining blockers: none
