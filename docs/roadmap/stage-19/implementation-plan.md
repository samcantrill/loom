# Roadmap Stage 19 Implementation Plan: Reliability Policies And Transactions

Status: Phase 6 in_progress
Roadmap stage: `v19`
Planning document: `docs/roadmap/stage-19/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 6 in_progress
Blockers:

- None. Implementation-plan quality gate passed on 2026-05-16 after
  `loom_plan_reviewer` review, bounded refinement, and confirmation review.

## Summary

- Goal: implement the core reliability fact layer for retry policy, timeout
  policy, failure classification, status detail, stage-attempt transactions,
  retry decisions, timeout outcomes, narrow lease compatibility, diagnostics,
  and read-only inspection.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-19/planning.md`; FR-1 through FR-10 are closed.
- Approved behavior: retry is opt-in and conservative; timeout is reliability
  policy, not resource policy; executors report facts while runner/authority
  code owns retry actions; stable run/stage status enums remain unchanged;
  reliability facts are durable store/read-model records, not event logs,
  status metadata, or executor-log parsing.
- Source behavior confirmation: complete in the planning artifact after user
  approval of the behavior baseline, structured examples, validation strategy,
  and six-phase split.
- Key design constraints: keep `loom` domain-neutral, dependency-light,
  import-light, fake/local-test-first, authority-compatible, and explicit about
  Stage 20 event-sink and Stage 21 cleanup boundaries.
- Source design-agreement gate: confirmed. Use import-light
  `loom.pipeline.reliability` models/protocols, authored config under
  `runtime.reliability` and
  `runtime.stage_options.<stage>.reliability`, runner-owned automation in
  `loom.pipeline.execution`, store-owned persistence in `loom.pipeline.stores`,
  and diagnostics/CLI as readers.
- Future-roadmap impact: Stage 20 can project committed reliability facts into
  runtime events and observe-only sinks; Stage 21 can consume transaction and
  cleanup-outcome facts for retention/cleanup planning without Stage 19
  deleting data.
- Reusable interface, adapter, or protocol assumptions: generic
  `FailureClassifier`, `RetryPolicyEvaluator`, timeout capability/adapter,
  reliability store/read facets, transaction store, and runner reliability
  controller protocols operate on plain records and existing run/stage/attempt
  references.
- Examples covered: reliability policy merge; retry-safe failed stage; unsafe
  transaction retry denial; unsupported timeout; enforced/delegated/observed/
  unsupported/timed-out outcomes; commit failure; status detail without enum
  churn; lease compatibility diagnostic; read-only reliability inspection.
- Source phase shaping: six phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-16.
- Out of scope: event grammar and event sinks; callback failure policy;
  plugin-discovered sink loading; cleanup, deletion, retention enforcement,
  and run-collection GC; service-specific notifications or telemetry clients;
  advanced backoff, cross-run retry budgets, resource-aware retry escalation,
  executor migration, and scheduler-health orchestration.

## Goal

Stage 19 turns deferred reliability concerns into explicit, inspectable, and
conservative runtime facts. Users should be able to understand why a stage
failed, whether timeout policy was supported or applied, whether staged outputs
became authoritative, and why a retry did or did not happen.

The implementation must make those answers available from Loom records and
read models, not from backend-specific logs or hidden executor control flow.
Retry automation is the only runtime-changing automation in scope, and it is
allowed only when explicit policy, failure classification, remaining attempt
budget, and transaction safety all agree.

## Context

Current source already has the foundations Stage 19 must build on:

- `loom.pipeline.status` owns stable `RunStatus`, `StageStatus`,
  `RunStatusRecord`, and `StageStatusRecord` vocabulary.
- `loom.pipeline.runtime` owns runtime options, stage-level options, executor
  descriptors, and capability diagnostics. Current runtime parsing explicitly
  rejects or defers legacy `retry`, `timeout`, and `timeout_seconds` fields.
- `loom.pipeline.execution` owns runner orchestration, lifecycle persistence,
  stage attempts, executor requests/results, and output commit behavior.
- `loom.pipeline.executors` owns executor implementations such as local and
  subprocess executors. Executors already return structured execution results
  and failures.
- `loom.pipeline.stores` owns local and authority-compatible lifecycle records,
  read models, attempt allocation, output commits, leases, recovery records,
  materialized refs, and cleanup candidates.
- `loom.diagnostics` and CLI modules present existing status, preflight, and
  logs-style information.

The planning artifact records that Stage 18 details are not available in this
checkout. Stage 19 therefore must use generic executor/capability facts and
fake/local tests for container and scheduler compatibility until a later Stage
18 artifact locks backend specifics.

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-19/planning.md`
- Functionality and behavior baseline: complete. The notes lock opt-in retry,
  stable status enums plus detail records, timeout as reliability policy,
  durable transaction and decision records, runner/authority-owned actions,
  narrow lease reuse, preflight diagnostics, and narrow inspection.
- Design-safety review: passed. The follow-up recheck after structured
  examples and validation were added also passed with no blockers.
- Examples and validation strategy: complete. Validation is fake/local-first,
  no-network by default, and covers import boundaries, policy merge, failure
  classification, transactions, store/read facets, retry safety, timeout
  support, lease compatibility, preflight diagnostics, inspection, and final
  suite evidence.
- Phase shaping: complete. Six phases are recorded below.
- Implementation readiness blockers from planning: none.
- Accepted risks and revisit triggers:
  - Stage 18 container execution specifics are unavailable. Revisit if Stage
    18 introduces timeout or failure contracts that contradict the generic
    Stage 19 capability model.
  - Exact local reliability-record file layout remains implementation-plan or
    phase detail. Revisit before persistence work begins if versioned,
    inspectable, authority-compatible records cannot be represented cleanly.
  - Rollback/cleanup wording means transaction failure and cleanup-outcome or
    cleanup-candidate facts only. Revisit during Stage 21 cleanup planning for
    physical deletion, retention enforcement, and GC.

## Desired Outcome

When all phases are complete:

- `loom.pipeline.reliability` provides import-light policy, record, and
  protocol types for reliability policy, retry policy, timeout policy, failure
  classification, status detail, stage-attempt transactions, retry decisions,
  timeout outcomes, classifier/evaluator/capability adapters, and store/read
  facets.
- Runtime config accepts `runtime.reliability` and
  `runtime.stage_options.<stage>.reliability`, including documented merge
  semantics, unknown-field rejection, omitted-versus-disabled behavior, and
  clear total-attempt semantics for retry policy.
- Stores persist versioned reliability facts associated with existing
  run/stage/attempt/status/lease/output-commit records.
- Execution lifecycle records transaction/status-detail facts around attempts
  without expanding `RunStatus` or `StageStatus`.
- Timeout support is capability-aware and records enforced, delegated,
  observed, unsupported, and timed-out outcomes.
- Retry decisions are persisted before any next attempt, and automatic retry
  remains runner/authority-owned.
- Users can inspect reliability policy, status detail, transaction state,
  retry decisions, timeout outcomes, and unsupported-policy diagnostics through
  read models and narrow status/logs-style CLI presentation where included.

## Non-Goals

- No runtime event grammar, `EventSink`, `EventSinkRegistry`, callback failure
  records, or plugin-discovered event sink loading.
- No event-driven external actions, notifications, webhooks, Slack/email/Teams/
  PagerDuty clients, W&B/MLflow/OpenTelemetry clients, or hosted telemetry.
- No cleanup execution, deletion, retention enforcement, or run-collection GC.
- No advanced retry backoff, cross-run retry budgets, adaptive retry policy, or
  resource-aware retry escalation.
- No executor migration, scheduler-health orchestration, worker-daemon
  prefetch, or broad queue-controller behavior.
- No domain-specific failure categories, metrics, model/checkpoint semantics,
  or project-specific policy keys.
- No real cluster, container, cloud, network, or optional-SDK dependency in
  default tests or default imports.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep `loom.pipeline.reliability` import-light. It must not import concrete
  executors, stores, diagnostics, CLI modules, plugin discovery, optional
  backends, or service integrations.
- Keep authored configs trusted project code, while keeping persisted
  reliability facts strict, plain-data serializable, and safe to inspect.
- Preserve stable status enums. Failure reason, lifecycle phase, and messages
  belong in status detail/classification records.
- Keep timeout separate from resource admission wait time and authority service
  operational timeouts.
- Persist reliability facts as store/read-model records associated with
  authority facts. Do not treat `events.jsonl`, status metadata, or executor
  logs as the source of truth.
- Keep Stage 20/21 compatibility explicit through stable IDs, timestamps,
  run/stage/attempt refs, transaction IDs, reason codes, and causal links.
- Every phase PR must run targeted validation, `make validate-pr`, and
  `make test-summary` unless a command is unavailable and the phase PR records
  the reason.

## Design Principles

- Facts before actions. Reliability policy, classification, transaction,
  timeout, and decision records should exist before runner automation depends
  on them.
- Conservative by default. Retry is off unless explicit policy and recorded
  facts allow another attempt.
- Source of truth stays authoritative. Stores own durable reliability facts;
  diagnostics, CLI, run catalogs, and future events project from them.
- Generic before backend-specific. Executor-specific details live in metadata
  or capability facts, not public core policy keys.
- Observability without mutation. Inspection surfaces read reliability records;
  they do not trigger retry, cleanup, or external callbacks.
- Narrow adapters over broad frameworks. Add protocols only where they remove
  real coupling between runtime, execution, stores, and future executor
  adapters.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Reliability subsystem | Add import-light `loom.pipeline.reliability` for records and protocols | Later phases can share types without importing runner/store/executor code |
| Public config path | Use `runtime.reliability` with `runtime.stage_options.<stage>.reliability` overrides | Avoids top-level deferred `retry`/`timeout` fields and avoids overloading resource requests |
| Retry attempt count | Lock `max_attempts` as the Stage 19 public retry policy field, meaning total attempts including the initial attempt | Prevents ambiguity between retries and attempts before runtime parsing lands |
| Status detail | Keep `RunStatus` and `StageStatus` stable; add classification/detail records | Prevents backend-specific enum churn and keeps future event/status compatibility |
| Persistence | Store reliability facts as versioned records keyed by run/stage/attempt/transaction references | Stage 20 and Stage 21 can consume committed facts without parsing logs |
| Retry ownership | Runner/authority code evaluates and schedules next attempts; executors report facts | Avoids hidden executor retry loops and keeps decisions durable |
| Timeout model | Timeout is reliability policy with capability/outcome records | Keeps wall-time behavior distinct from resource admission and authority control timeouts |
| Lease scope | Reuse or narrowly harden existing lease contracts | Avoids a parallel global lease model |
| Inspection | Add read-only read-model/API and narrow CLI presentation where useful | Provides user-visible diagnosis without broad mutation commands |

## Conflicts And Tradeoffs

- Adding `loom.pipeline.reliability` creates a new package boundary. The value
  is shared vocabulary and protocols; the risk is subsystem creep. Phase 1 must
  enforce import-boundary tests and stop conditions.
- Persisting reliability records before runner behavior adds upfront store work,
  but it prevents retry automation from being implemented around transient
  in-memory state.
- Generic timeout outcomes may not capture every scheduler/container nuance.
  The accepted tradeoff is to keep backend-specific details in metadata until a
  concrete executor need requires stronger contracts.
- Narrow CLI inspection may be deferred if read models alone satisfy the
  user-visible outcome. If deferred, Phase 6 must explain the decision and
  still leave users with a stable Python/API inspection path.
- Fake/local validation avoids heavy dependencies and unavailable environments,
  but it cannot prove every future container or scheduler edge case. Opt-in
  acceptance tests remain outside the default gate.

## Maintainability Assessment

The staged structure is maintainable because it separates public contracts,
persistence, lifecycle classification, timeout diagnostics, retry automation,
and final inspection/docs. The most important maintainability constraint is
keeping `loom.pipeline.reliability` as plain records and protocols rather than
a runtime orchestration package. The second major constraint is keeping store
facts authoritative so later event, cleanup, and diagnostics work does not
reconstruct behavior from logs or status messages.

## Extensibility Assessment

The plan keeps future executors, remote stores, Stage 20 event sinks, Stage 21
cleanup, and service-specific integrations possible without adding those
features now. Future adapters should report generic failure, timeout,
transaction, lease, and capability facts into the Stage 19 records. Future
event sinks should observe Stage 20 event projections over these facts, not
drive core retry or transaction behavior.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Exact local reliability-record file layout deferred | Phase 2 should choose it with current store code in hand, while this plan locks the authority-compatible record contract | Phase 2 cannot represent versioned, inspectable records without changing broader store layout |
| Stage 18 container specifics unavailable | The planning artifact explicitly accepts generic timeout/failure capability assumptions until Stage 18 is detailed | Stage 18 introduces container timeout or failure facts that conflict with Stage 19 records |
| Rollback means recorded transaction failure and cleanup outcome/candidate facts | Physical deletion and retention enforcement are Stage 21 scope | Stage 21 cleanup/retention planning begins or Stage 19 implementation needs destructive behavior |
| Backend-specific timeout metadata remains plain detail | Avoids overfitting before real executor needs prove a stronger schema | Fake/local/subprocess tests cannot express useful timeout diagnostics without backend-specific public fields |
| Advanced retry orchestration deferred | Roadmap explicitly defers backoff, cross-run budgets, and resource escalation | Users need policy beyond conservative max-attempt retry after Stage 19 lands |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by `loom_plan_reviewer`; one blocking finding reported
  for retry attempt field ambiguity
- Refinement pass: complete. The plan now locks `max_attempts` as the public
  retry attempt-count field with total-attempt semantics.
- Confirmation review: complete by `loom_plan_reviewer`; no remaining blocking
  or material findings
- Automatic merge mode: enabled after phase PRs pass automated review,
  validation, CI, and target-branch gates
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Default phase base/target: `develop`; each phase execution planner must
  recompute and record the actual stack predecessor and PR target before
  creating its worktree.
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Workflow path: expanded path is expected for every phase because Stage 19
  creates public records/protocols, persisted facts, execution semantics,
  diagnostics, and possible CLI/read-model behavior.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `reliability-contracts-runtime-policy` | merged | `codex/reliability-contracts-runtime-policy` | [#176](https://github.com/samcantrill/loom/pull/176) | `loom.pipeline.reliability`, `loom.pipeline.runtime` | Add import-light contracts and public runtime policy parsing/merge | Package, unit, runtime contract tests, `make validate-pr`, `make test-summary` | Policy merge, disabled/unset policy, import boundary |
| 2 | `reliability-persistence-read-models` | merged | `codex/reliability-persistence-read-models` | [#177](https://github.com/samcantrill/loom/pull/177) | `loom.pipeline.stores`, read models | Persist and read versioned reliability facts | Store unit/contract/integration tests, `make validate-pr`, `make test-summary` | Status detail, transaction, timeout, retry-decision records |
| 3 | `transaction-failure-classification` | merged | `codex/transaction-failure-classification` | [#178](https://github.com/samcantrill/loom/pull/178) | `loom.pipeline.execution`, lifecycle, status detail | Record transaction/classification facts around attempts | Classifier unit tests, lifecycle/store integration tests, `make validate-pr`, `make test-summary` | Commit failure, status detail without enum churn |
| 4 | `timeout-capability-diagnostics` | merged | `codex/timeout-capability-diagnostics` | [#179](https://github.com/samcantrill/loom/pull/179) | runtime capabilities, executors, diagnostics, lease compatibility | Add timeout outcomes and reliability diagnostics | Capability, preflight, fake/subprocess tests, `make validate-pr`, `make test-summary` | Unsupported timeout, distinct timeout outcomes, lease diagnostic |
| 5 | `retry-decisions-runner-automation` | merged | `codex/retry-decisions-runner-automation` | [#180](https://github.com/samcantrill/loom/pull/180) | runner, lifecycle, retry evaluator | Implement conservative runner-owned retry | Evaluator matrix, fake runner integration tests, `make validate-pr`, `make test-summary` | Retry-safe failed stage, unsafe transaction denial |
| 6 | `reliability-inspection-finalization` | in_progress | `codex/reliability-inspection-finalization` | pending | read models, CLI if included, docs, final validation | Expose read-only inspection and finalize docs/evidence | Read-model/CLI/docs tests, `make validate-pr`, `make test-summary` | Read-only reliability inspection |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Plan quality gate | Repository workflow | `loom_plan_reviewer` review found one blocker, bounded refinement locked `max_attempts`, and confirmation review found no remaining findings | resolved |

## Phase 1: Reliability Contracts And Runtime Policy

Status: merged
Slug: `reliability-contracts-runtime-policy`
Branch: `codex/reliability-contracts-runtime-policy`
Worktree: `/home/samcantrill/work/loom-worktrees/reliability-contracts-runtime-policy`
PR: https://github.com/samcantrill/loom/pull/176
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public config and
record/protocol surface

### Scope

- Goal: add import-light reliability policy, record, and protocol contracts
  plus the public runtime config surface.
- Files/modules owned:
  - new `src/loom/pipeline/reliability.py` or
    `src/loom/pipeline/reliability/` package
  - `src/loom/pipeline/runtime/options.py`
  - `src/loom/pipeline/runtime/_models.py`
  - package/API exports only where they match existing package patterns
  - package, runtime, and reliability unit/contract tests
- Behavior implemented:
  - Reliability policy, retry policy, timeout policy, failure category,
    failure classification, status detail, stage-attempt transaction, retry
    decision, timeout outcome, and protocol shapes.
  - Runtime parsing, serialization, unknown-field rejection, and merge rules
    for `runtime.reliability` and stage-level reliability overrides.
  - Omitted-versus-explicit-disabled policy semantics.
  - `max_attempts` as the public retry attempt-count field, with total-attempt
    semantics including the initial attempt.
- Decisions applied: public config path, import-light subsystem boundary,
  stable records, no resource timeout.
- Examples or docs covered: representative authored policy and reliability
  policy merge.
- Out of scope:
  - Store persistence.
  - Runner retry behavior.
  - Timeout enforcement.
  - Preflight/CLI presentation.
  - Event sinks and cleanup/deletion.
- Dependencies: confirmed planning artifact and current runtime option models.

### Tasks

- Choose module/package shape for `loom.pipeline.reliability` and record the
  choice in the phase execution plan.
- Define strict record schemas, enums, and protocols with `to_dict`/`from_dict`
  behavior consistent with existing Loom value records.
- Add runtime option fields and merge helpers for run-level defaults and
  stage-level overrides.
- Document disabled/unset semantics and unknown-field rejection.
- Add package/import-boundary tests proving reliability contracts do not import
  concrete executors, stores, diagnostics, CLI, plugins, authority service
  clients, or optional backends.
- Keep legacy deferred `retry`, `timeout`, and `timeout_seconds` paths rejected
  unless mapped deliberately into the new runtime reliability path.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package tests/unit/loom/pipeline/test_runtime_options.py tests/unit/loom/pipeline/test_runtime_config.py tests/contracts/test_runtime_options_contract.py` | Target package import boundaries and runtime option parsing/round trips | yes |
| `uv run pytest tests/unit/loom/pipeline tests/contracts/test_executor_capabilities_contract.py` | Target reliability records and adjacent capability contracts as added | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: runtime reliability policies round trip strictly, reject
  unknown fields, merge run/stage policy correctly, and distinguish omitted
  from disabled.
- Design-decision evidence: `loom.pipeline.reliability` stays import-light and
  timeout is not added to `ResourceRequest`.
- Future-roadmap compatibility evidence: records include stable IDs, reason
  codes, refs, and causal-link fields needed by Stage 20/21.
- Interface, adapter, or protocol reuse evidence: classifier/evaluator/
  timeout/store/controller protocols are generic and plain-record based.
- Documentation evidence: docstrings or docs explain policy shape and attempt
  count semantics.
- Domain-neutrality evidence: examples use generic stages and executor facts.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: used by manager-local type/lint cleanup
- PR review budget: used by `loom_phase_reviewer` pre-submit review
- Blocker-resolution budget: 2/3 used
- Pre-submit blocker gate: implementation-plan quality gate must pass
- Merge record: merged into `develop` at
  `c7415fd10e285d181481249f3fc06c7104908e17` on 2026-05-16 after automated
  review, local validation, and GitHub CI passed. Branch retained because
  Phase 2 was already stacked on `codex/reliability-contracts-runtime-policy`.

### Risks And Stop Conditions

- Risks: public policy overreach, import cycles, ambiguous retry count
  semantics, resurrecting deprecated top-level fields.
- Stop conditions: implementation needs concrete executor/store imports in
  reliability contracts; config merge cannot distinguish omitted and disabled;
  timeout must be represented as a resource field for correctness.
- Assumptions: exact persistence file layout remains Phase 2 scope.

### Completion Summary

- Implementation: complete. Added `loom.pipeline.reliability` policy, record,
  and protocol contracts plus `runtime.reliability` and stage override
  parsing/merge behavior.
- Validation: complete. Targeted suites passed; `make validate-pr` passed
  Ruff, Pyright, default suite (`1782` passed), config-extra (`446` passed),
  and build; `make test-summary` passed all suites.
- PR: opened at https://github.com/samcantrill/loom/pull/176 targeting
  `develop`.
- Merge: merged into `develop` at
  `c7415fd10e285d181481249f3fc06c7104908e17`.
- Follow-up: Phase 2 was created as stacked continuation from the Phase 1
  branch and will need retarget/rebase maintenance before merge eligibility if
  it remains stacked.

## Phase 2: Reliability Persistence And Read Models

Status: merged
Slug: `reliability-persistence-read-models`
Branch: `codex/reliability-persistence-read-models`
Worktree: `/home/samcantrill/work/loom-worktrees/reliability-persistence-read-models`
PR: https://github.com/samcantrill/loom/pull/177
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates store/read contracts
and durable record layout

### Scope

- Goal: add store/read-model facets for reliability facts without replacing
  existing authority records.
- Files/modules owned:
  - `src/loom/pipeline/stores/` reliability persistence modules or facets
  - `src/loom/pipeline/stores/read_models.py`
  - local run-store and authority-compatible store tests
  - store contract tests for reliability facts
- Behavior implemented:
  - Append/read surfaces for policy facts, status details, transaction records,
    retry decisions, and timeout outcomes.
  - Versioned records keyed by run URI, stage name, attempt, transaction ID,
    timestamps, reason codes, and causal references.
  - Association with existing `StageAttempt`, `OutputCommitRecord`,
    `LeaseRecord`, status records, materialized refs, and cleanup candidates.
  - Local and fake/authority-compatible read-model coverage.
- Decisions applied: store-owned durable facts, authority compatibility,
  event-ready identity without event grammar.
- Examples or docs covered: durable status detail, transaction, timeout, and
  retry-decision records.
- Out of scope:
  - Runner retry automation.
  - Timeout enforcement.
  - Failure classifier integration.
  - Broad CLI commands.
  - Cleanup deletion or retention enforcement.
- Dependencies: Phase 1 reliability records/protocols.

### Tasks

- Select concrete local materialization layout for reliability facts and record
  why it is versioned, inspectable, and authority-compatible.
- Add append/read methods or facets without changing existing authority truth
  semantics.
- Add read-model records or projections for policy, status detail,
  transaction, retry decision, and timeout outcome facts.
- Add strict serialization and backward-compatible missing-record behavior.
- Add store contract tests for local and fake authority paths.
- Prove reliability facts do not depend on `events.jsonl`, status metadata, or
  executor logs.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/contracts/test_run_store_authority_contract.py tests/contracts/test_authoritative_read_model_contract.py` | Target store/read-model persistence and authority compatibility | yes |
| `uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution_failures.py` | Exercise local store compatibility with existing lifecycle records | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: reliability records append/read strictly and preserve
  associations with existing stage attempt, output commit, lease, and status
  facts.
- Design-decision evidence: facts are not status metadata, event logs, or
  executor-log parsing.
- Future-roadmap compatibility evidence: Stage 20/21 can project or consume
  records through stable references.
- Interface, adapter, or protocol reuse evidence: local and fake/authority
  implementations use the same read/write contract.
- Documentation evidence: store docstrings or feature docs identify the source
  of truth and local materialization behavior.
- Domain-neutrality evidence: records use generic runtime failure/transaction
  vocabulary.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: unused; targeted and final validation passed
- PR review budget: used by manager-local automated review; no blocking findings
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; Phase 1 merged and Phase 2 targets `develop`
- Merge record: merged into `develop` at
  `7467afc7eb2253bb14ecfde00a885ce6698e457a` on 2026-05-16 after automated
  manager review, local validation, and GitHub CI passed.

### Risks And Stop Conditions

- Risks: duplicating authority truth, schema churn, local-only persistence,
  coupling read models to event logs.
- Stop conditions: reliability records require replacing core store contracts;
  local layout cannot support future authority projection; records need
  destructive cleanup behavior.
- Assumptions: physical cleanup remains Stage 21 and is represented only as
  facts/candidates here.

### Completion Summary

- Implementation: complete. Added store-owned reliability policy facts, status
  details, stage-attempt transactions, retry decisions, and timeout outcomes
  across local, in-memory, SQLite, and service authority-compatible store paths.
- Validation: complete. `make validate-pr` passed Ruff, Pyright, default suite
  (`1788 passed, 26 skipped, 18 deselected`), config-extra suite
  (`446 passed, 1825 deselected`), and build. `make test-summary` passed
  overall (`2262 passed, 18 skipped, 1841 deselected`).
- PR: opened at https://github.com/samcantrill/loom/pull/177 targeting
  `develop`.
- Merge: merged into `develop` at
  `7467afc7eb2253bb14ecfde00a885ce6698e457a`.
- Follow-up: Phase 3 can branch from updated `develop`; no successor branch
  depends on the Phase 2 branch.

## Phase 3: Transaction And Failure Classification Integration

Status: merged
Slug: `transaction-failure-classification`
Branch: `codex/transaction-failure-classification`
Worktree: `/home/samcantrill/work/loom-worktrees/transaction-failure-classification`
PR: https://github.com/samcantrill/loom/pull/178
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase changes execution lifecycle and
failure semantics

### Scope

- Goal: record transaction/status-detail facts around stage attempts and
  classify failures without changing status enums.
- Files/modules owned:
  - `src/loom/pipeline/execution/lifecycle.py`
  - `src/loom/pipeline/execution/runner.py` only for transaction/classifier
    integration, not retry loops
  - `src/loom/pipeline/execution/models.py` only for fact plumbing if needed
  - `src/loom/pipeline/status.py` only for compatibility helpers if needed
  - execution, lifecycle, status, and store tests
- Behavior implemented:
  - Transaction begin/prepared/running/staged/commit/failure/cleanup-outcome
    recording around stage attempt lifecycle.
  - Default failure classifier over `ExecutionFailure`, exit code, signal,
    cancellation, executor metadata, store commit failures, timeout outcomes
    when available, and plain detail.
  - Status detail persistence before final failed status where applicable.
  - Commit failure behavior that does not mark partial outputs authoritative.
- Decisions applied: stable status enums, transaction facts before retry,
  cleanup facts without deletion.
- Examples or docs covered: transaction commit failure and status detail
  without enum churn.
- Out of scope:
  - Automatic retry.
  - Timeout enforcement implementation.
  - Stage 21 deletion or retention behavior.
  - Event emission.
- Dependencies: Phases 1 and 2.

### Tasks

- Define final transaction state names and causal ordering in the phase
  execution plan before implementation.
- Wire transaction writes around lifecycle paths for success, failure,
  cancellation/interruption, and commit failure.
- Add default failure classification helpers and status detail writing.
- Preserve existing `RunStatus`/`StageStatus` serialization and public enum
  behavior.
- Add tests proving commit failures and ambiguous outputs are not treated as
  authoritative.
- Add integration coverage using fake/local runner paths.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/execution tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/stores` | Target lifecycle, classifier, status, and store behavior | yes |
| `uv run pytest tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py` | Exercise local/subprocess failure and commit paths | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: success, failure, cancellation, commit failure, and
  cleanup-outcome facts are recorded in order and inspectable.
- Design-decision evidence: stable status enums are preserved and detail
  records carry reason/category data.
- Future-roadmap compatibility evidence: transaction records include causal
  links and cleanup-outcome/candidate facts for Stage 20/21.
- Interface, adapter, or protocol reuse evidence: classifier consumes generic
  execution facts and metadata.
- Documentation evidence: docs or docstrings explain transaction ordering and
  status-detail layering.
- Domain-neutrality evidence: failure categories are generic runtime categories.

### Phase Workflow State

- Phase execution plan: complete at
  `docs/roadmap/stage-19/phases/transaction-failure-classification.md`
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: unused; implementation-pass fixes resolved targeted validation findings
- PR review budget: used by manager-local automated review; no blocking findings
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed; Phases 1 and 2 are merged into `develop`
- Merge record: merged into `develop` at
  `b78d6d588b7e634e8d31ef02eccc7a101587b547` on 2026-05-16 after automated
  manager review, local validation, and GitHub CI passed.

### Risks And Stop Conditions

- Risks: incorrect lifecycle ordering, status enum churn, output-authority
  ambiguity, hidden retry behavior leaking in early.
- Stop conditions: transaction writes cannot be made idempotent or ordered;
  status detail requires changing public status enum values; cleanup needs
  physical deletion.
- Assumptions: timeout outcome classification can accept absent timeout facts
  until Phase 4 lands.

### Completion Summary

- Implementation: complete. Added stateful stage-attempt transactions, execution-owned failure classification, lifecycle transaction writes, and authority-backed reliability delegation without changing `RunStatus` or `StageStatus`.
- Validation: complete. `make validate-pr` passed Ruff, Pyright, default suite (`1791 passed, 26 skipped, 18 deselected`), config-extra suite (`446 passed, 1828 deselected`), and build. `make test-summary` passed all suite groups.
- PR: opened at https://github.com/samcantrill/loom/pull/178 targeting `develop`
- Merge: merged into `develop` at
  `b78d6d588b7e634e8d31ef02eccc7a101587b547`.
- Follow-up: Phase 4 can branch from updated `develop`; no successor branch
  depends on the Phase 3 branch.

## Phase 4: Timeout Capability And Reliability Diagnostics

Status: merged
Slug: `timeout-capability-diagnostics`
Branch: `codex/timeout-capability-diagnostics`
Worktree: `/home/samcantrill/work/loom-worktrees/timeout-capability-diagnostics`
PR: https://github.com/samcantrill/loom/pull/179
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase crosses runtime capability,
executor, diagnostics, and lease-compatibility surfaces

### Scope

- Goal: add capability-aware timeout outcomes and cheap reliability
  diagnostics.
- Files/modules owned:
  - `src/loom/pipeline/runtime/capabilities.py`
  - `src/loom/pipeline/executors/` timeout-capability plumbing where feasible
  - `src/loom/pipeline/execution/` timeout outcome recording hooks
  - `src/loom/diagnostics/` preflight/readiness modules
  - `src/loom/pipeline/stores/coordination.py` and lease tests only for
    narrow compatibility diagnostics if needed
- Behavior implemented:
  - Timeout support/outcome records for enforced, delegated, observed,
    unsupported, and timed-out behavior.
  - Fake executor and subprocess-style timeout behavior where feasible.
  - Preflight/runtime diagnostics for unsupported retry, timeout, transaction,
    and lease policies.
  - Lease compatibility diagnostics using existing lease records/protocols
    before adding any fields.
  - Documentation separating reliability timeout from resource admission wait
    time and authority service operational timeouts.
- Decisions applied: timeout as reliability policy, no resource timeout field,
  narrow lease reuse/hardening.
- Examples or docs covered: unsupported timeout, distinct timeout outcomes,
  and lease compatibility diagnostic.
- Out of scope:
  - Scheduler-health orchestration.
  - Executor migration.
  - Resource-aware retry escalation.
  - Real cluster/container requirements in default tests.
  - Event sinks.
- Dependencies: Phases 1 through 3.

### Tasks

- Add timeout capability/outcome vocabulary and map current executor facts into
  it without requiring every executor to enforce timeouts.
- Decide whether subprocess timeout support is implemented in this phase or
  represented through fake/subprocess-style adapter tests only; record the
  decision in the phase execution plan.
- Add preflight checks that remain cheap by default and produce explicit
  diagnostics for unsupported/partial reliability policies.
- Recheck existing `LeaseRecord`, `ResourceLeaseRecord`, coordination, and
  authority lease diagnostics before adding fields.
- Add tests proving no timeout field is added to `ResourceRequest` and
  operational authority/resource timeouts remain separate.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/test_executor_capabilities.py tests/contracts/test_executor_capabilities_contract.py tests/unit/loom/diagnostics tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py` | Target capability and diagnostics behavior | yes |
| `uv run pytest tests/unit/loom/pipeline/executors tests/contracts/test_workspace_coordination_contract.py tests/unit/loom/pipeline/stores/test_sqlite_coordination.py` | Target fake/subprocess timeout and lease compatibility paths as changed | yes |
| `uv run pytest tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/integration/diagnostics/test_cli_preflight.py tests/integration/pipeline/test_runtime_capabilities_integration.py` | Exercise preflight and runtime capability integration | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: enforced, delegated, observed, unsupported, and timed-out
  outcomes are distinct and persisted/readable.
- Design-decision evidence: timeout remains reliability policy and no
  `ResourceRequest` timeout field is introduced.
- Future-roadmap compatibility evidence: records are generic enough for Stage
  18 containers and Stage 20 event projection.
- Interface, adapter, or protocol reuse evidence: fake and subprocess-style
  paths use the same timeout capability/outcome shape.
- Documentation evidence: docs distinguish reliability timeout from
  resource/authority operational timeouts.
- Domain-neutrality evidence: diagnostics use generic executor/capability
  language.

### Phase Workflow State

- Phase execution plan: complete at
  `docs/roadmap/stage-19/phases/timeout-capability-diagnostics.md`
- Planning/refinement budget: expanded path; draft and refine complete by
  manager-local planning
- Implementation/refinement budget: not needed; targeted validation and PR gate
  passed without a refinement blocker
- PR review budget: used by manager-local automated review
- Blocker-resolution budget: 0/3 used
- Pre-submit blocker gate: Phases 1 through 3 merged or valid stack
  predecessors
- Merge record: merged into `develop` at
  `068e2b4a5055d25d71069d1a43d42e28eaccf672` on 2026-05-16 after
  manager-local automated review, local validation, GitHub CI `checks`
  success, and target-branch verification. No successor branch depends on the
  Phase 4 branch.

### Risks And Stop Conditions

- Risks: confusing timeout domains, creating parallel lease concepts,
  requiring unavailable external environments, overfitting to one executor.
- Stop conditions: timeout cannot be expressed without changing resource
  admission semantics; lease compatibility needs a broad new lease model;
  default tests require real clusters or containers.
- Assumptions: backend-specific timeout details remain metadata until a later
  concrete executor phase requires stronger public schema.

### Completion Summary

- Implementation: complete. Added timeout support/outcome vocabulary,
  descriptor-level timeout support diagnostics, subprocess timeout
  enforcement, local unsupported-timeout metadata, lifecycle timeout outcome
  persistence, lease capability diagnostics, and docs clarifying timeout
  domain separation.
- Validation: complete. Focused package/unit/contract/integration batch passed
  with `189` tests; `make validate-pr` passed Ruff, Pyright, default suite
  (`1800` passed), config-extra (`446` passed), and build; `make
  test-summary` passed all suites.
- PR: opened at https://github.com/samcantrill/loom/pull/179 targeting
  `develop`.
- Merge: merged into `develop` at
  `068e2b4a5055d25d71069d1a43d42e28eaccf672`.
- Follow-up: Phase 5 can branch from updated `develop`; no Phase 4 stack
  maintenance or successor retargeting is required.

## Phase 5: Retry Decisions And Runner-Owned Automation

Status: merged
Slug: `retry-decisions-runner-automation`
Branch: `codex/retry-decisions-runner-automation`
Worktree: `/home/samcantrill/work/loom-worktrees/retry-decisions-runner-automation`
PR: [#180](https://github.com/samcantrill/loom/pull/180)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase introduces Stage 19's only
runtime-changing automation

### Scope

- Goal: implement conservative opt-in retry using persisted decisions and
  transaction safety evidence.
- Files/modules owned:
  - `src/loom/pipeline/execution/runner.py`
  - `src/loom/pipeline/execution/lifecycle.py`
  - retry evaluator implementation under `loom.pipeline.reliability` or
    execution-owned integration modules, preserving import direction
  - retry decision store/read tests
  - runner integration tests
- Behavior implemented:
  - Default retry evaluator over resolved policy, failure classification,
    attempt history, max attempts, transaction state, and timeout outcome.
  - Retry decisions persisted before any next-attempt scheduling.
  - Runner-owned next-attempt behavior for explicitly allowed retry only.
  - Denial behavior for disabled retry, exhausted attempts, non-retryable
    classification, validation/graph/config failures, cancellation, unsafe
    transaction state, and unsupported policy.
- Decisions applied: runner/authority-owned retry, no hidden executor retry,
  no event-triggered retry, retry off by default.
- Examples or docs covered: retry-safe failed stage and unsafe transaction
  retry denial.
- Out of scope:
  - Advanced backoff.
  - Cross-run retry budgets.
  - Resource-aware escalation.
  - Executor-local retry loops.
  - Event-sink-triggered retry.
  - Scheduler-health orchestration.
- Dependencies: Phases 1 through 4.

### Tasks

- Define evaluator decision matrix in the phase execution plan before
  implementation.
- Implement default evaluator as a pure decision over policy and stored facts.
- Persist allowed and denied decisions before scheduling any next attempt.
- Add runner integration for one or more additional attempts when allowed.
- Preserve existing failure behavior when retry policy is absent or disabled.
- Add tests that prove executors do not own high-level retry decisions.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/execution tests/unit/loom/pipeline tests/contracts/test_executor_contract.py` | Target evaluator, runner, lifecycle, and executor contract behavior | yes |
| `uv run pytest tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py` | Exercise local/subprocess retry and non-retry flows | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: no retry without policy; allowed retry starts exactly the
  recorded next attempt; denied retry records reason and stops.
- Design-decision evidence: retry decision is persisted before action and
  executors report facts only.
- Future-roadmap compatibility evidence: decisions include enough identity and
  causal references for Stage 20 event projection.
- Interface, adapter, or protocol reuse evidence: evaluator can be used with
  fake/local/subprocess-style facts without backend-specific policy keys.
- Documentation evidence: docs explain conservative retry defaults and denial
  reasons.
- Domain-neutrality evidence: retry examples use generic stage failures.

### Phase Workflow State

- Phase execution plan: complete at
  `docs/roadmap/stage-19/phases/retry-decisions-runner-automation.md`
- Planning/refinement budget: expanded path; draft and refine complete by
  manager-local planning
- Implementation/refinement budget: not needed; no formal refiner pass consumed
- PR review budget: used by manager-local automated review; no blocking
  findings remained after the runtime-option consistency fix
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 through 4 merged or valid stack
  predecessors
- Merge record: PR [#180](https://github.com/samcantrill/loom/pull/180)
  squash-merged into `develop` at
  `82fbd748afe0cf36aa5b69177711d3ff511f3485` after CI `checks` passed

### Risks And Stop Conditions

- Risks: retry loops causing duplicate outputs, in-memory decisions, executor
  retry ownership, accidental retry of validation/config/graph failures.
- Stop conditions: retry cannot be made safe from recorded transaction state;
  decision persistence cannot be guaranteed before scheduling; retry behavior
  requires event sinks or external callbacks.
- Assumptions: initial Stage 19 retry policy supports bounded total attempts
  only; advanced backoff and budgets remain deferred.

### Completion Summary

- Implementation: complete; runner-owned retry records allowed and denied
  decisions before scheduling additional attempts, keeps executors
  one-attempt-at-a-time, and preserves no-policy failure behavior.
- Validation: complete; targeted Phase 5 suite passed with `184 passed`;
  `make validate-pr` passed Ruff, Pyright, default tests, config-extra tests,
  and package build; `make test-summary` passed all suites with `2281 passed,
  18 skipped, 1859 deselected`.
- PR: opened as [#180](https://github.com/samcantrill/loom/pull/180) against
  `develop`
- Merge: PR [#180](https://github.com/samcantrill/loom/pull/180)
  squash-merged into `develop` at
  `82fbd748afe0cf36aa5b69177711d3ff511f3485`; GitHub CI `checks` passed
  before merge.
- Follow-up: Phase 6 can branch from updated `develop`; no Phase 5 stack
  successor depends on the merged branch.

## Phase 6: Read-Only Inspection, Documentation, And Final Validation

Status: in_progress
Slug: `reliability-inspection-finalization`
Branch: `codex/reliability-inspection-finalization`
Worktree: `/home/samcantrill/work/loom-worktrees/reliability-inspection-finalization`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase finalizes user-visible
inspection, docs, and suite evidence

### Scope

- Goal: expose reliability facts for users and complete documentation and
  validation evidence.
- Files/modules owned:
  - read-model presentation helpers under `loom.pipeline.stores`,
    `loom.runs`, or diagnostics only as appropriate
  - `src/loom/cli/` status/logs-style output only if materially useful
  - `docs/features/reliability.md`
  - `docs/features/execution.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - final package/docs/read-model/CLI tests
- Behavior implemented:
  - Read-only Python/API inspection for selected reliability policy, status
    detail, transaction records, retry decisions, timeout outcomes, and
    unsupported-policy diagnostics.
  - Narrow CLI status/logs-style presentation if it naturally fits existing
    commands; otherwise record why Python/read models satisfy Stage 19.
  - Feature docs and testing docs updated to describe final behavior,
    deferrals, and accepted risks.
  - Final validation evidence collected for PR preparation.
- Decisions applied: read-only inspection, no mutating retry/cleanup/event
  commands, Stage 20/21 boundaries.
- Examples or docs covered: read-only reliability inspection and final
  examples from the planning artifact.
- Out of scope:
  - Mutating retry commands.
  - Cleanup commands.
  - Event sink commands.
  - Service notifications or telemetry clients.
  - New provider/backend integrations.
- Dependencies: Phases 1 through 5.

### Tasks

- Add read-model accessors or presentation helpers for reliability facts.
- Decide in the phase execution plan whether CLI output is included. If
  included, keep it to existing status/logs-style commands and add CLI tests.
  If excluded, record how Python/read-model inspection satisfies the
  user-visible outcome.
- Update feature docs for final reliability behavior and explicit Stage 20/21
  deferrals.
- Add final package/import-boundary hardening if earlier phases exposed public
  names.
- Run final targeted checks, `make validate-pr`, and `make test-summary`.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package tests/contracts tests/unit/loom/pipeline tests/unit/loom/diagnostics tests/unit/loom/cli` | Broad package, contract, unit, diagnostic, and CLI coverage for final surface | yes |
| `uv run pytest tests/integration/pipeline tests/integration/diagnostics tests/e2e/test_cli_core.py tests/e2e/test_cli_runs_e2e.py` | Exercise local/read-model/CLI integration where changed | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: users can inspect policy, classification/status detail,
  transaction state, retry decisions, timeout outcomes, and unsupported-policy
  diagnostics.
- Design-decision evidence: inspection is read-only and does not add mutating
  retry, cleanup, or event-sink commands.
- Future-roadmap compatibility evidence: docs preserve Stage 20 event/sink and
  Stage 21 cleanup/retention boundaries.
- Interface, adapter, or protocol reuse evidence: presentation reads public
  read models instead of executor logs or store internals.
- Documentation evidence: feature docs and testing docs reflect final
  behavior, suite obligations, deferrals, and accepted debt.
- Domain-neutrality evidence: docs/examples stay generic and avoid
  service-specific semantics.

### Phase Workflow State

- Phase execution plan: completed in `docs/roadmap/stage-19/phases/reliability-inspection-finalization.md`
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: one pass available
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 through 5 merged or valid stack
  predecessors
- Merge record: pending

### Risks And Stop Conditions

- Risks: CLI surface grows too broad, docs imply cleanup/events are included,
  final validation exposes earlier import-boundary drift.
- Stop conditions: user-visible inspection requires mutating commands;
  read-model APIs cannot expose required facts without breaking store
  boundaries; final validation cannot run and no acceptable justification is
  available.
- Assumptions: narrow read models are sufficient if CLI presentation is not
  materially useful.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Cross-Phase Validation

- Full relevant test command: each phase PR must run targeted tests for its
  owned modules plus `make validate-pr`; PR preparation must run
  `make test-summary`.
- Docs/template checks: `git diff --check` for docs/code diffs, affected docs
  tests where present, and feature-doc consistency for reliability, execution,
  run-store, state, preflight, CLI, and testing.
- Domain-neutrality checks: no domain-specific failure categories, no service
  client dependencies, no ML/tracking terminology in core public APIs, and no
  real cluster/container/cloud/network dependency in default tests.
- Import-boundary checks: `loom.pipeline.reliability` remains import-light;
  diagnostics/CLI read public records/read models; stores do not import CLI;
  executors do not own retry policy.
- Example/demo checks: representative runtime policy merge, failed-attempt
  flow, unsupported timeout, unsafe transaction retry denial, and read-only
  inspection.
- Manual review focus: policy merge semantics, record versioning, lifecycle
  ordering, transaction safety, timeout domain separation, retry decision
  ordering, Stage 20/21 boundaries, and accepted debt.

## Plan Quality Gate

- Status: passed
- Required reviewer: `loom_plan_reviewer`
- Required sequence: one review pass, one bounded refinement pass if blocking
  or material findings are reported, and one confirmation review.
- Review scope: planning readiness, maintainability, extensibility, future
  compatibility, conflicting design choices, accepted technical debt, test
  strategy, reviewability, and no unresolved `blocked` or `needs discussion`
  decisions.
- Stage-planning readiness checks: verify functionality-to-design
  traceability, completed design-safety review and recheck, future-roadmap
  impact, reusable interface/adapter/protocol assumptions, validation
  strategy, phase shaping, and no planning blockers.
- Stop condition: do not create Phase 1 execution plans or begin product
  implementation while blocking plan-review findings remain unresolved.
- Review pass: complete. The reviewer reported one blocking finding: the draft
  delegated the public retry attempt field name to Phase 1.
- Refinement pass: complete. The plan now locks `max_attempts` as the Stage 19
  public retry policy field, meaning total attempts including the initial
  attempt.
- Confirmation review: complete. No blocking or material findings remain.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Public retry attempt field was still delegated to Phase 1 | blocker | Locked `max_attempts` as the Stage 19 public retry policy field with total-attempt semantics, including the initial attempt | resolved |
| Plan quality gate pending | blocker | Confirmation review completed with no remaining blocking or material findings | resolved |

Gate result:

- Status: passed
- Review evidence: `loom_plan_reviewer` initial review found one blocking
  retry attempt field ambiguity; bounded refinement locked `max_attempts` as
  the public field with total-attempt semantics; confirmation review found no
  remaining blocking or material findings.
- Accepted risks:
  - Stage 18 details are roadmap-only until a Stage 18 artifact exists.
  - Exact reliability record file layout remains phase detail.
  - Rollback/cleanup means transaction failure and cleanup-outcome/candidate
    facts only, not deletion or retention enforcement.
  - Backend-specific timeout metadata remains plain detail until a later
    executor phase needs stronger contracts.
- Revisit triggers:
  - Reliability policy merge cannot distinguish omitted policy from explicit
    disablement.
  - Existing lease records cannot express named resource keys, slot counts,
    duration, renewal, and renewal failure diagnostics without a public
    contract change.
  - Stage 20 cannot project events from Stage 19 committed facts without
    adding event-specific fields to Stage 19 records.
  - Stage 18 introduces container timeout or failure contracts that contradict
    the generic Stage 19 capability model.

## Final Approval

- Approval status: approved for Phase 1 execution planning
- Approved scope: six-phase Stage 19 plan as recorded above
- Accepted risks: Stage 18 details are roadmap-only until a Stage 18 artifact
  exists; exact reliability record file layout remains phase detail; rollback/
  cleanup means transaction failure and cleanup-outcome/candidate facts only;
  backend-specific timeout metadata remains plain detail until a later executor
  phase needs stronger contracts
- Deferred items: event grammar/sinks, external actions, cleanup/deletion/
  retention/GC, service-specific integrations, advanced retry orchestration,
  executor migration, scheduler-health automation, and real external-environment
  default tests
