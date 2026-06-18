# Phase 3 Execution Plan: Runtime Dispatch From Committed Facts

## Metadata

- Status: final phase execution plan; scope-complete for implementation
- Feature focus: Runtime Events
- PR title: `Runtime Events - Phase 3: Runtime Event Dispatch`
- Branch: `codex/runtime-event-dispatch`
- Worktree: `/home/samcantrill/work/loom-worktrees/runtime-event-dispatch`
- Phase execution plan path: `docs/roadmap/stage-20/phases/runtime-event-dispatch.md`
- Full plan: `docs/roadmap/stage-20/implementation-plan.md`
- Source phase: Phase 3, `runtime-event-dispatch`
- Stack predecessor: none; Phase 2 PR
  [#188](https://github.com/samcantrill/loom/pull/188) merged before Phase 3
  PR preparation
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root PR; merge-eligible after the PR targets `develop`,
  automated review passes, local validation passes, GitHub CI passes, and the
  phase remains scoped to Phase 3
- Workflow path: expanded path
- Plan quality gate: verified passed in the implementation plan on 2026-05-17
- Draft pass: completed by manager on 2026-05-17
- Refine pass: completed by manager on 2026-05-17; Phase 2 stack and CI state
  incorporated
- Setup limitations: Phase 2 PR [#188](https://github.com/samcantrill/loom/pull/188)
  merged into `develop` at
  `f0c9f36c5253f490508e3cb8207a2f21da44cb94`; this branch was replayed onto
  `origin/develop` before Phase 3 validation and PR preparation.
- Blockers: none

## Objective

Wire runtime event append/projection and explicit event sink dispatch into
runtime paths after durable facts exist. Sinks must observe committed facts and
best-effort callback failures without becoming part of run correctness.

## Scope

- Add a central append/project/dispatch helper in `loom.pipeline.execution`
  that accepts explicit registry/context inputs and preserves ordering:
  committed fact, durable event append/projection, then sink dispatch.
- Extend runtime configuration/plumbing just enough for callers/tests to supply
  an explicit `EventSinkRegistry` and an event persistence mode. Do not load
  plugins and do not create a global registry.
- Dispatch run/stage lifecycle events through the helper when an explicit
  registry is present.
- Persist callback failures through the Phase 2 observer-fact store facets.
- Allow explicit persistence-disabled dispatch with non-durable event identity
  and warning diagnostics; do not fabricate durable store sequences.
- Project available committed reliability/submission/transaction facts only
  where stable existing records already exist. If Stage 19 fact names are not
  available in code, document deferral rather than inventing new reliability
  semantics.
- Add focused unit and integration tests proving sinks see committed facts,
  dispatch continues after callback failure, failures are persisted
  best-effort, and non-durable dispatch is visibly non-durable.

## Out Of Scope

- Plugin entry point loading or ambient discovery.
- Service-specific sinks, notification clients, hosted telemetry, webhooks,
  OpenTelemetry, streaming systems, or metric extraction.
- Strict audit mode.
- Cleanup/deletion/retention behavior.
- Event-driven mutation of plans, configs, artifacts, statuses, retry
  decisions, transactions, submitted operations, or run metadata.
- Broad CLI/diagnostics presentation beyond minimal warning objects needed by
  explicit persistence-disabled tests.

## Design Contract

Runtime dispatch must keep these boundaries:

- The execution path commits or confirms the source fact before creating an
  event observed by sinks.
- Durable dispatch uses the persisted `PipelineEventRecord` reference returned
  by the store.
- Non-durable dispatch uses an `EventReference` with
  `durability="non_durable"` and positive in-process `dispatch_sequence`; its
  `sequence` stays absent.
- Callback failures are recorded as `EventSinkFailureRecord` facts through the
  narrow store/context surface and do not recursively dispatch ordinary runtime
  events.
- Sink contexts expose only event identity and observer-link/failure recorder
  methods. They must not expose a full run store, authority store, runner,
  artifact writer, status mutator, retry mutator, transaction mutator, or
  arbitrary metadata writer.

## Implementation Steps

1. Add execution-local dispatch/context helpers, including non-durable
   reference creation and per-run dispatch sequence allocation.
2. Add explicit registry/persistence plumbing to the runtime entry point used
   by local serial execution tests.
3. Route existing run/stage lifecycle event emission through the helper when a
   registry is supplied, preserving current event append/read behavior when no
   registry is supplied.
4. Record callback failures best-effort through `append_event_sink_failure`
   without changing run status or raising from sink callbacks.
5. Add tests for committed-fact ordering, callback failure persistence,
   observer-link writeback, and explicit non-durable dispatch identity.
6. Update docs/phase notes with validation and any Stage 19 projection deferral.

## Test Plan

### Unit Suite

- Status: required
- Expected paths:
  `tests/unit/loom/pipeline/execution/test_eventing.py`,
  `tests/unit/loom/pipeline/execution/test_runner.py`,
  `tests/unit/loom/pipeline/execution/test_lifecycle.py`,
  `tests/unit/loom/pipeline/test_event_sinks.py`
- Required assertions: durable append happens before sink dispatch; failing
  sinks do not stop later sinks or fail runs; observer-link writeback uses only
  the narrow context; non-durable dispatch references omit durable sequence and
  carry `dispatch_sequence`.

### Integration Suite

- Status: required
- Expected paths:
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_local_execution_resume.py`,
  `tests/integration/pipeline/test_local_execution_failures.py`,
  `tests/integration/pipeline/test_local_stores.py`
- Required assertions: local execution dispatches sinks only after committed
  run/stage facts, persisted callback failures are readable after execution,
  observer failures do not change run correctness, and resume/failure paths keep
  event ordering stable.

### Diagnostics Suite

- Status: required if persistence-disabled warnings add diagnostics models
- Expected paths: `tests/unit/loom/diagnostics`,
  `tests/integration/diagnostics`
- Deferral reason if unchanged: no diagnostics modules are modified.

### E2E And Opt-In Suites

- Status: deferred
- Deferral reason: no plugin loading, CLI presentation, service SDK, remote
  service, or opt-in backend behavior is introduced in this phase.

## Validation Commands

```sh
uv run pytest tests/unit/loom/pipeline/execution/test_eventing.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/test_event_sinks.py
uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_stores.py
uv run pytest tests/unit/loom/diagnostics tests/integration/diagnostics
make validate-pr
make test-summary
```

## Budget Status

- Phase implementation refinement: unused
- PR review: used by manager local review on 2026-05-17; no blocking findings
  found, scope confirmed limited to Phase 3 runtime dispatch, request
  plumbing, tests, and phase artifacts
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager on 2026-05-17
- Final phase execution plan: completed by manager on 2026-05-17
- Implementation summary: added `RuntimeEventDispatcher`,
  `EventDispatchWarning`, execution-local sink context writeback, explicit
  `RunRequest.event_sink_registry` and `event_persistence` plumbing, runner and
  lifecycle dispatch wiring, non-durable `EventReference` dispatch identity,
  best-effort callback failure persistence, and unit/integration coverage for
  durable ordering, observer links, callback failures, and non-durable
  dispatch. Stage 19-specific retry, timeout, transaction, and submission event
  names remain deferred; this phase preserves committed lifecycle fact ordering
  and does not invent new reliability event semantics.
- Implementation validation: targeted unit dispatch suite passed with 68
  tests; targeted local integration/store suite passed with 1 test and 3
  optional-dependency modules skipped in the plain dev environment; diagnostics
  suite passed with 100 tests when run with `--extra config`; `make
  validate-pr` passed Ruff, Pyright, default harness, config-extra harness, and
  build; `make test-summary` passed with overall 2381 passed, 21 skipped, and
  1957 deselected.
- Refinement summary: not needed; targeted validation and final PR gates passed
  after implementation-local type fixes before the implementation commit.
- Blocker-resolution summary: none needed
- PR preparation: PR body artifact prepared at
  `docs/roadmap/stage-20/phases/runtime-event-dispatch-pr-body.md`; PR
  [#189](https://github.com/samcantrill/loom/pull/189) opened against
  `develop`; verification confirmed base `develop`, head
  `codex/runtime-event-dispatch`, state `OPEN`, and GitHub CI `checks` in
  progress
- Stack maintenance: Phase 2 merged before Phase 3 PR preparation; Phase 3 was
  replayed onto `origin/develop` and no longer depends on
  `codex/event-sink-registry-observer-facts`
- Remaining blockers: none
