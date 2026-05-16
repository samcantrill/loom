# Phase 1 Execution Plan: Reliability Contracts And Runtime Policy

## Metadata

- Status: refined phase execution plan
- Feature focus: Reliability Policies And Transactions
- PR title: `Reliability Policies And Transactions - Phase 1: Contracts And Runtime Policy`
- Branch: `codex/reliability-contracts-runtime-policy`
- Worktree: `/home/samcantrill/work/loom-worktrees/reliability-contracts-runtime-policy`
- Phase execution plan path: `docs/roadmap/stage-19/phases/reliability-contracts-runtime-policy.md`
- Full plan: `docs/roadmap/stage-19/implementation-plan.md`
- Source phase: Phase 1, `reliability-contracts-runtime-policy`
- Stack predecessor: none; this is the root Stage 19 phase
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root PR is eligible to merge into `develop` only after phase implementation, targeted validation, `make validate-pr`, `make test-summary`, automated review, and CI pass with no blockers
- Workflow path: expanded path
- Successor dependency notes: Phase 2 may stack on this branch only after the Phase 1 PR is open or prepared and recorded by the manager; no successor depends on this planning branch yet
- Plan quality gate: passed on 2026-05-16 in the selected implementation plan
- Plan quality gate loop budget: implementation-plan review, bounded refinement, and confirmation review are complete; no blocking findings remain
- Draft pass: completed by `loom_phase_planner` in this assignment
- Refine pass: completed by `loom_phase_planner` in this assignment
- Setup limitations: branch/worktree were created from freshly fetched `origin/develop` commit `427b352f4b14e80b2972dd5600c25c1e29ffb6c1` because the control checkout's local `develop` is behind and has unrelated local/untracked planning artifacts. `origin/develop` does not contain `docs/roadmap/stage-19/`, so this branch carries forward the local untracked Stage 19 planning and implementation-plan artifacts from the control checkout plus the roadmap split edits needed for Stage 19/20/21 consistency. Unrelated local Stage 17/18 artifacts and workflow prompt/template changes are not part of this phase plan.
- Blockers: none

## Objective

Create the import-light reliability contract surface and public runtime policy path that later Stage 19 phases can use for persistence, transaction recording, timeout diagnostics, retry decisions, and read-only inspection. This phase locks the plain record/protocol vocabulary and runtime parsing/merge semantics without adding store persistence, runner retry behavior, timeout enforcement, CLI presentation, events, or cleanup.

## Full-Plan Context

Stage 19 implements reliability policies and transactions in six phases. Phase 1 provides the shared contracts and `runtime.reliability` policy surface. Phase 2 persists and reads reliability facts, Phase 3 records transaction/classification facts in execution, Phase 4 adds timeout capability diagnostics, Phase 5 adds conservative runner-owned retry, and Phase 6 finalizes inspection/docs. Stage 20 owns runtime events and event sinks. Stage 21 owns cleanup, deletion, retention, and run-collection GC.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: the manager assigned root Phase 1 and required creation from freshly fetched `origin/develop` commit `427b352`; there is no earlier unmerged Stage 19 phase
- Retarget/rebase plan after predecessor merge: none for Phase 1; successor phases should target this branch only if Phase 1 is open/prepared but not yet merged
- Branch cleanup constraints: do not delete the branch while any successor branch targets or depends on it

## Source Phase Summary

- Goal: add import-light reliability policy, record, and protocol contracts plus the public runtime config surface.
- Required scope: new `loom.pipeline.reliability` package, runtime option fields and merge helpers, strict serialization, unknown-field rejection, disabled/unset policy semantics, `max_attempts` total-attempt semantics, package/API tests, runtime unit/contract tests, and import-boundary checks.
- Required checkpoints: choose package shape, keep legacy deferred `retry`/`timeout` fields rejected outside the new path, prevent timeout from becoming a resource field, and document the public policy shape.
- Acceptance criteria: runtime policies round trip strictly; run/stage policy merge is deterministic; omitted and explicit disabled policy differ; reliability contracts stay import-light; records include stable identity/reference fields for Stage 20/21; examples remain domain-neutral.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/runtime/options.py` owns `RunOptions`, `StageRuntimeOptions`, safe metadata, and stage-option validation; `src/loom/pipeline/runtime/_models.py` still rejects `retry`, `timeout`, and `timeout_seconds` on `RuntimeRequest`; `src/loom/pipeline/resources.py` owns `ResourceRequest` and must not gain a timeout field; `src/loom/pipeline/__init__.py` and `src/loom/pipeline/runtime/__init__.py` are explicit public facades.
- Existing tests or harness behavior: `tests/unit/loom/pipeline/test_runtime_options.py` already checks strict unknown-field rejection, round trips, safe metadata, and legacy `retry` rejection; `tests/contracts/test_runtime_options_contract.py` locks plain-data serialization; package tests lock public exports and import boundaries; `tests/contracts/test_executor_capabilities_contract.py` and `tests/unit/loom/pipeline/test_runtime_resources.py` protect resource/capability behavior.
- Import-boundary or dependency constraints: `loom.pipeline.reliability` may depend on foundational value, serialization, timestamp, status, and typing modules, but must not import concrete executors, stores, diagnostics, CLI, plugins, authority service clients, optional backends, or config extras.

## In-Scope Work

- Add `src/loom/pipeline/reliability/` as the chosen package shape for policy, record, enum, and protocol contracts.
- Define strict plain-data reliability policy models for retry and timeout plus generic failure classification, status detail, stage-attempt transaction, retry decision, and timeout outcome record shapes.
- Define generic protocols for classifier, retry evaluator, timeout capability/adapter, reliability record store/read facets, transaction store, and runner reliability controller handoff. Protocols are contracts only in this phase.
- Add `runtime.reliability` and `runtime.stage_options.<stage>.reliability` support through `RunOptions` and `StageRuntimeOptions`.
- Implement run-level default plus stage-level override merge semantics, including omitted versus explicit-disabled policy behavior.
- Lock `max_attempts` as total attempts including the initial attempt; validation must reject ambiguous or invalid attempt counts.
- Keep legacy top-level `retry`, `timeout`, and `timeout_seconds` fields rejected unless they are deliberately represented under the new reliability path.
- Add focused tests and docstrings or feature-doc snippets that explain the public policy path, disabled/unset semantics, and attempt-count semantics.

## Out-of-Scope Work

- Store persistence, local reliability file layout, read models, and authority-compatible write/read methods.
- Runner retry loops, next-attempt scheduling, retry-decision persistence, transaction writes during execution, or failure classifier integration with execution.
- Timeout enforcement, subprocess timeout behavior, scheduler/container timeout behavior, preflight diagnostics, or lease compatibility changes.
- CLI output, run-catalog projection, broad documentation finalization, runtime events, event sinks, callback failure records, plugin loading, cleanup, deletion, retention, and GC.
- New optional dependencies, service-specific integrations, external telemetry, and real cluster/container/network validation.

## Assumptions

- Authored configs remain trusted project code, but runtime/reliability records still need strict plain-data validation and useful errors.
- `RuntimeResourceError` remains the runtime parsing error surface unless existing local patterns clearly require a narrower reliability-specific exception.
- Stage 18 specifics are unavailable in this checkout, so records and protocols stay generic over executor names, capability facts, exit/signal data, and metadata.
- Package exports should follow existing facade patterns. Do not export reliability symbols from root `loom`; expose `loom.pipeline.reliability` and add `loom.pipeline`/runtime facade exports only if package API tests show that is the local public-surface convention.

## Scope Contract

Public behavior:

- `runtime.reliability` maps to run-level reliability defaults. `runtime.stage_options.<stage>.reliability` overrides only that stage.
- A missing reliability block means no local override; at the run level this resolves to conservative defaults: retry disabled and no timeout policy.
- A retry or timeout block with `enabled: false` explicitly disables that policy and masks inherited policy for the stage.
- A retry policy with `max_attempts` greater than `1` permits retry only as policy input. Actual retry remains later Phase 5 behavior and still requires classification, attempt budget, and transaction safety.
- `max_attempts` means total attempts including the initial attempt; valid values are positive integers and `1` means no additional attempt.
- Timeout remains reliability policy. Do not add timeout to `ResourceRequest`, resource admission behavior, or authority service operational timeout settings.
- Unknown fields must be rejected in reliability policy and record parsing. Legacy `retry`, `timeout`, and `timeout_seconds` outside the new path must not be silently accepted.

Module boundaries:

- `loom.pipeline.reliability` is a plain-record and protocol package. It must not own runner actions, store implementation, diagnostics, CLI presentation, event grammar, plugin loading, or cleanup behavior.
- `loom.pipeline.runtime` may import reliability policy models to parse, merge, serialize, and expose safe metadata.
- Later execution/store/diagnostics phases may import the reliability contracts, but the contracts must not import those layers.

Data shapes and edge cases:

- Reliability records must carry schema version, stable IDs where applicable, timestamps, run/stage/attempt references, transaction IDs where applicable, reason codes, and optional causal links so Phase 20 events and Phase 21 cleanup can project from committed facts later.
- Backend-specific data belongs in plain metadata/detail fields, not in public policy keys or domain-specific categories.
- Status detail and failure classification records explain stable `RunStatus`/`StageStatus` values; they do not add backend-specific status enum values.
- This phase may define transaction and retry-decision record schemas, but it must not persist them or make runtime decisions from them yet.

## Design Impact

- Maintainability: centralizes Stage 19 vocabulary in one import-light package and keeps runtime parsing separate from execution/store behavior.
- Extensibility: future stores, executors, timeout adapters, retry evaluators, and Stage 20 event projection can share one plain contract surface.
- Domain neutrality: policy names, failure categories, examples, and metadata stay generic to pipeline execution and avoid research-domain or service-specific semantics.
- Source-tree boundaries: runtime may depend on reliability contracts; reliability contracts may not depend on runtime integration, stores, executors, diagnostics, CLI, plugins, or authority service implementations.

## Future Compatibility

- Phase 2 can persist the same record shapes without changing public policy names.
- Phase 3 and Phase 5 can consume classifier/evaluator/transaction protocols without redefining retry ownership.
- Phase 4 can attach timeout capability/outcome facts without moving timeout into resources.
- Stage 20 can project events from reliability records because IDs, timestamps, reason codes, refs, transaction IDs, and causal links are present without defining an event grammar now.
- Stage 21 can consume transaction cleanup-outcome/candidate facts later; this phase must not imply physical deletion or retention enforcement.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put all reliability contracts in `execution` | Would make runner code the public contract and couple future stores/events to execution internals. |
| Add top-level authored `retry` or `timeout` fields | The plan locks `runtime.reliability` and stage overrides as the public path; legacy top-level fields are currently deferred/rejected. |
| Add timeout to `ResourceRequest` | Confuses reliability wall-time policy with resource admission/resource hints and violates the Stage 19 timeout boundary. |
| Hide facts in status metadata, events, or executor logs | Later phases need durable typed records and authority-compatible reads, not inferred messages. |
| Export a root `loom.reliability` API now | Reliability is pipeline-specific and should first stabilize under `loom.pipeline.reliability`. |
| Accept multiple aliases for disabled/unset policy | Ambiguous authored config would make policy merge and support diagnostics harder to review. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No intentional Phase 1 debt planned | This phase is contract/config foundation only; persistence, runner behavior, diagnostics, and inspection are intentionally separate phases rather than debt | Any required Phase 1 deferral beyond the recorded phase boundaries must be documented in implementation completion notes and carried to the owning later phase. |

## Reviewability

- Expected PR size and shape: a small public-contract PR with a new reliability package, runtime option integration, focused tests, and minimal docs/docstrings. No runner/store/CLI implementation should appear.
- Files and areas to inspect: `src/loom/pipeline/reliability/`, `src/loom/pipeline/runtime/options.py`, `src/loom/pipeline/runtime/config.py`, `src/loom/pipeline/runtime/profiles.py`, `src/loom/pipeline/runtime/metadata.py` if merge/resolution metadata changes, `src/loom/pipeline/runtime/_models.py`, facade exports, package tests, runtime unit tests, and contract tests.
- Scope-control checks: no `ResourceRequest` timeout field, no execution retry loop, no store persistence, no CLI command/output, no event/sink contract, no cleanup behavior, no optional dependencies, no imports from forbidden runtime layers into reliability contracts.

## Implementation Steps

1. Add the reliability package and public contract exports with import-boundary tests first.
2. Define policy, record, enum, and protocol shapes with strict `to_dict`/`from_dict` behavior and plain-data validation.
3. Integrate `ReliabilityPolicy` into `RunOptions` and `StageRuntimeOptions`, including safe metadata and strict unknown-field behavior.
4. Add deterministic run/stage policy merge helpers and resolved-runtime metadata only where the current runtime option/profile patterns require them.
5. Add focused docs/docstrings and examples for `runtime.reliability`, stage overrides, disabled/unset semantics, and `max_attempts`.
6. Add targeted package, unit, contract, and integration coverage, then leave final broad validation for PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_api.py`, and any new `tests/package/test_pipeline_reliability_api.py`
- Required assertions or deferral reason: importing `loom.pipeline.reliability` is cheap; it does not import execution, executors, stores, diagnostics, CLI, plugins, authority service clients, config extras, or optional backends; public exports match existing package facade conventions.

### Unit Suite

- Status: required
- Expected paths: new reliability unit tests under `tests/unit/loom/pipeline/reliability/` or `tests/unit/loom/pipeline/test_reliability.py`, plus `tests/unit/loom/pipeline/test_runtime_options.py`, `tests/unit/loom/pipeline/test_runtime_metadata.py` if metadata changes, and `tests/unit/loom/pipeline/test_runtime_resources.py`
- Required assertions or deferral reason: policy and record round trips; schema version checks; unknown-field rejection; omitted versus explicit-disabled merge semantics; `max_attempts` total-attempt validation; timeout not accepted as a resource field; legacy deferred fields remain rejected outside the new runtime path; safe metadata omits raw detail where existing patterns require summarization.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_runtime_options_contract.py`, new `tests/contracts/test_reliability_contract.py`, and `tests/contracts/test_executor_capabilities_contract.py` if capability-facing assertions are added
- Required assertions or deferral reason: reliability policy documents are stable plain data; record/protocol shapes expose identity/reference/causal fields needed by later phases; runtime option serialization remains stable; executor capability/resource contracts do not gain retry ownership or resource timeout semantics.

### Integration Suite

- Status: required for runtime config/profile merge behavior
- Expected paths: `tests/integration/pipeline/test_runtime_options_integration.py`, `tests/integration/pipeline/test_runtime_profiles_integration.py`, and `tests/integration/pipeline/test_runtime_capabilities_integration.py` only if capability validation is touched
- Required assertions or deferral reason: authored runtime config/profile inputs can carry run-level reliability policy and stage overrides through existing parsing/merge paths. If implementation does not touch profile/config integration, record that narrow deferral and keep unit/contract coverage mandatory.

### E2E Suite

- Status: deferred
- Expected paths: none for Phase 1
- Required assertions or deferral reason: no CLI, runner behavior, executor behavior, store persistence, or user workflow changes are implemented in this phase. E2E coverage belongs to later phases when inspection or execution behavior changes.

### Opt-In Suites

- Status: deferred
- Markers affected: no real cluster, container, cloud, network, service, telemetry, or optional-SDK markers
- Required assertions or deferral reason: Phase 1 is pure contracts/runtime parsing and must remain default-suite and fake/local-test only.

## Risks

- Public config names are durable; ambiguous disabled/unset semantics would create long-term compatibility cost.
- A broad reliability package could become a dumping ground for runner, store, diagnostics, event, or cleanup behavior.
- Record schemas may overfit future phases if they omit stable refs/causal fields or encode backend-specific public fields too early.
- Runtime merge changes may accidentally revive deprecated top-level `retry`/`timeout` fields or add timeout to resources.
- Import facade changes can accidentally pull execution/store/CLI layers into package import paths.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/pipeline/test_runtime_options.py tests/unit/loom/pipeline/test_runtime_metadata.py tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/reliability
uv run pytest tests/contracts/test_runtime_options_contract.py tests/contracts/test_reliability_contract.py tests/contracts/test_executor_capabilities_contract.py
uv run pytest tests/integration/pipeline/test_runtime_options_integration.py tests/integration/pipeline/test_runtime_profiles_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with package/import-boundary tests and reliability contracts, then runtime option parsing, then merge helpers/resolved metadata, then docs/docstrings and targeted tests.
- Tests to run with each slice: package import-boundary tests after exports, reliability unit/contract tests after record shapes, runtime option tests after parsing/merge, integration tests after config/profile merge changes.
- Decisions the executor must not revisit: use `src/loom/pipeline/reliability/` as the package shape; use `runtime.reliability` and `runtime.stage_options.<stage>.reliability`; keep `max_attempts` as total attempts including the initial attempt; keep retry disabled by default; keep timeout out of `ResourceRequest`; keep events/sinks, persistence, runner retry, CLI, and cleanup out of scope.
- Conditions that require stopping for the manager: reliability contracts need concrete executor/store/CLI imports; policy merge cannot distinguish omitted from explicit disabled; implementation requires timeout as a resource field; Stage 20 event projection would require Stage 19 to define event grammar; or the branch contains unrelated Stage 17/18/workflow artifacts.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: completed in this artifact
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- Blocker-resolution summary: none used during planning
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none
