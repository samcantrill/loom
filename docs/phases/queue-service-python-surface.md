# Phase 6 Execution Plan: Queue Service, Client, And Python Control Surface

## Metadata

- Status: implemented
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 6: Queue Service, Client, And Python Control Surface`
- Branch: `codex/queue-service-python-surface`
- Worktree: `/home/samcantrill/work/loom-worktrees/queue-service-python-surface`
- Phase execution plan path: `docs/phases/queue-service-python-surface.md`
- Full plan: `docs/implementation-plans/implementation-plan-v11.md`
- Source phase: Phase 6, `v11` Queue Service, Client, And Python Control Surface
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root v11 phase after Phase 5 merge; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase introduces the public queue control surface, config loading, and service/client/controller boundaries
- Successor dependency notes: Phase 7 branches from `develop` if this phase merges, otherwise from this branch after PR open/validation
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 5 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: completed locally on 2026-05-13 after inspecting Phase 5 queue records, config optional-dependency boundaries, and roadmap v11 notes
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Add a Python-first queue control surface that can load explicit queue specs, create and control a queue service, enqueue and inspect items through a client facade, and run fake queued work through daemon-style and foreground-drain controller entrypoints without collapsing queue policy into authority storage.

## Full-Plan Context

Phase 5 established durable queue records and a SQLite repository. This phase makes those records usable through a service/client/controller boundary and a normalized queue config model. Phase 7 owns managed resources and a real local launcher, Phase 8 owns delegated SLURM dispatch, and Phase 9 owns CLI and operator-facing polish.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 5 merged into `develop`
- Why this base branch is correct: Phase 5 merge metadata is on `develop`, and this phase depends on the public queue records/repository that Phase 5 introduced
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: add queue service/client boundaries and a clean Python control surface without merging queue policy into authority.
- Required scope: service lifecycle semantics, queue client methods, Python controller entrypoints, explicit-path queue config loading, and optional `loom[config]` composition normalization.
- Required checkpoints: queue code remains dependency-light and avoids private authority repository imports; foreground drain leaves no locally managed fake claims orphaned.
- Acceptance criteria: queue can be configured, started, controlled, and drained from Python against fake work; authority private storage remains untouched by queue code.

## Current Source And Harness Findings

- `src/loom/queue/models.py` already exposes versioned pools, queues, items, launch contracts, claims, dispatch handles, cancellation, audit, and recovery records.
- `src/loom/queue/_sqlite.py` exposes a repository with enqueue, read, FIFO claim, dispatch-handle persistence, terminal completion, cancellation, audit, and recovery scans.
- The repository does not persist queue definitions, so service configuration remains an explicit trusted runtime input for this phase.
- `loom.config` keeps optional YAML/OmegaConf/Pydantic dependencies behind lazy symbol access; queue config loading must not import those through the `loom.queue` root.
- Package boundary tests already require `loom.queue` to avoid eager imports of config, authority, private authority storage, executor, server, and CLI layers.

## In-Scope Work

- Add normalized queue config/spec records for service DB path, pools, queues, and controller options.
- Add explicit-path trusted YAML loading that validates and normalizes into the same queue spec model.
- Add a lazy optional `loom[config]` composition path that accepts composed config output and normalizes the same queue section without importing config dependencies eagerly.
- Add a queue service facade over `QueueRepository` with lifecycle state, topology validation, enqueue/read/audit/recovery/cancel/claim/dispatch/complete operations, and service status.
- Add a queue client facade that can call the service boundary for enqueue, inspect, cancel, service lifecycle, and controller operations.
- Add a Python controller with fake dispatch adapter support for one-step daemon-style dispatch and foreground-drain compatibility mode.

## Out-of-Scope Work

- Real local process launching, process-group tracking, authority resource leasing, or local drift detection.
- SLURM, SSH, or delegated launch adapters.
- CLI commands, supervisor integration, bulk submission, retries, priorities, fairness, or external brokers.
- Any queue import of private authority repository modules or queue-owned mutation of authority records.

## Assumptions

- The Phase 6 service is an in-process Python boundary; process management and CLI wrappers arrive later.
- Queue definitions remain explicit trusted configuration in service memory until a later phase needs durable topology administration.
- Controller dispatch uses fake adapter behavior only and records queue-local dispatch/completion evidence.
- Service startup may report existing recovery records but does not reinterpret or repair active work until real adapters arrive.

## Scope Contract

The public Python surface must normalize queue configuration before service start, enforce one queue per pool, enqueue only against configured queues, expose reads through queue item IDs, and support cancellation with queue-local evidence. The controller may claim only configured pools, must record a dispatch handle before terminal completion, and foreground drain must finish with no active recovery records for fake work it manages. Queue modules must not import `loom.authority._repository` or other private authority storage, and config dependency access must stay lazy.

## Design Impact

- Maintainability: separates queue control APIs from repository persistence and from future adapter/resource policy.
- Extensibility: controller and client facades provide a transport-neutral shape that a CLI, service process, or remote client can reuse.
- Domain neutrality: APIs operate on queues, pools, run intents, launch contracts, and adapter evidence without project-specific workload assumptions.
- Source-tree boundaries: queue config and service code stay under `loom.queue`; optional config composition is imported only inside the relevant function.

## Future Compatibility

The controller should accept injected adapters and a bounded loop interface so later local and SLURM adapters can replace fake behavior without changing service/client calls. Config normalization should keep plain-data shapes stable and avoid implicit discovery so later bundle or deployment tooling can call the same loader.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| CLI-first queue setup and enqueueing | Phase 6 is explicitly Python-first; the thin operational CLI wrapper is Phase 9. |
| Implicit queue config discovery | The implementation plan rejects implicit discovery in favor of explicit paths. |
| Persist queue topology in the Phase 5 SQLite schema now | Durable topology administration is not needed for fake service control and would broaden schema scope. |
| Build service behavior directly into the repository | The plan calls for a service/client boundary above durable records. |
| Import config composition from the queue root | That would break optional dependency and import-boundary expectations. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Service boundary is in-process only | It satisfies Python control and fake lifecycle tests without premature transport design | Phase 9 CLI/supervisor or a remote queue service needs process/transport adapters |
| Queue topology is service configuration rather than durable admin state | Phase 5 did not include topology persistence and this phase only needs trusted configured operation | Operators need runtime queue creation or topology audit history |
| Fake adapter completes work synchronously | Real launch semantics belong to Phase 7 and Phase 8 | Managed local/SLURM dispatch lands |

## Reviewability

- Expected PR size and shape: focused queue package additions plus package/unit/contract/integration tests.
- Files and areas to inspect: new queue config/service/client/controller modules, `src/loom/queue/__init__.py`, package import boundaries, and queue service/controller tests.
- Scope-control checks: no CLI, no real process launching, no authority private storage imports, no resource leasing, no SLURM adapter implementation.

## Implementation Steps

1. Add queue config/spec models and loaders with lazy YAML/config composition access.
2. Add queue service lifecycle and operation methods over the existing repository protocol.
3. Add queue client facade and inspection result records.
4. Add fake controller dispatch and foreground-drain entrypoints.
5. Export the public queue control symbols without breaking lightweight root imports.
6. Add package, unit, contract, and integration tests for the new control surface.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `loom.queue` remains lightweight, exports the queue control symbols, and queue modules do not import private authority storage or optional config dependencies eagerly.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/queue/test_config.py`, `tests/unit/loom/queue/test_service_client.py`, `tests/unit/loom/queue/test_controller.py`
- Required assertions or deferral reason: config normalization and explicit YAML loading, service/client lifecycle and enqueue/inspect/cancel behavior, controller one-step and foreground-drain fake dispatch behavior.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_queue_config_contract.py`, `tests/contracts/test_queue_python_api_contract.py`
- Required assertions or deferral reason: public queue spec and Python API result shapes remain stable for later phases.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/queue/test_service_lifecycle.py`, `tests/integration/queue/test_fake_controller.py`
- Required assertions or deferral reason: service restart/recovery status, configured enqueue against SQLite repository, fake daemon-style dispatch, and foreground-drain compatibility without orphaned claims.

### E2E Suite

- Status: deferred
- Expected paths: not required
- Required assertions or deferral reason: no CLI, service process, or full user workflow is in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM, SSH, hosted queue, or site-specific dependency behavior is introduced.

## Risks

- Public Python names introduced here will be reused by later CLI and adapter work; keep them narrow and transport-neutral.
- Config normalization must be strict enough to catch bad topology without trying to own the full project config language.
- Fake foreground drain must avoid leaving claimed/dispatched items active because later local managed work will rely on this invariant.
- Root package exports must remain lightweight even as service/control symbols become public.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/unit/loom/queue/test_config.py tests/unit/loom/queue/test_service_client.py tests/unit/loom/queue/test_controller.py tests/contracts/test_queue_config_contract.py tests/contracts/test_queue_python_api_contract.py tests/integration/queue/test_service_lifecycle.py tests/integration/queue/test_fake_controller.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: config/spec first, service/client second, controller/fake adapter third, tests and exports last.
- Tests to run with each slice: config unit/contract tests after loader work; service/client tests after service operations; controller/integration tests after fake dispatch work; package tests after exports.
- Decisions the executor must not revisit: no real adapters, no CLI, no topology persistence schema, no authority private storage, no queue-side resource leasing.
- Conditions that require stopping for the manager: needing public transport design, changing Phase 5 queue record semantics, or needing authority mutation to satisfy fake service behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted and full validation passed
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: added normalized queue service config records and
  explicit-path YAML/config-extra normalization helpers; added an in-process
  queue service facade, transport-neutral client facade, and Python controller
  with fake dispatch adapter support; exported the public control symbols while
  keeping root queue imports lightweight; added package, unit, contract, and
  integration coverage for config loading, service lifecycle, client
  operations, fake daemon-style dispatch, foreground drain, and restart
  recovery status.
- Implementation validation: targeted Phase 6 pytest passed with 56 passed and
  2 skipped in the no-extra environment; targeted config-extra queue loader
  pytest passed with 5 passed; targeted Ruff and Pyright on queue code/tests
  passed; `make validate-pr` passed with Ruff, Pyright, the default harness
  reporting 1405 passed, 21 skipped, and 14 deselected, the config-extra
  harness reporting 434 passed and 1437 deselected, and `uv build` passing;
  `make test-summary` passed overall with 1866 passed, 14 skipped, and 1449
  deselected.
- Refinement summary: no separate refinement pass was needed after validation.
- Blocker-resolution summary: none.
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: none.
