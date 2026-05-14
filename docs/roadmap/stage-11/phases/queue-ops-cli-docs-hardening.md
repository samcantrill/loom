# Phase 9 Execution Plan: Operational UX, CLI, Docs, And Hardening

## Metadata

- Status: pr_open
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 9: Operational UX, CLI, Docs, And Hardening`
- Branch: `codex/queue-ops-cli-docs-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/queue-ops-cli-docs-hardening`
- Phase execution plan path: `docs/roadmap/stage-11/phases/queue-ops-cli-docs-hardening.md`
- Full plan: `docs/roadmap/stage-11/implementation-plan.md`
- Source phase: Phase 9, `v11` Operational UX, Minimal CLI Wrapper, Docs, And Hardening
- PR: https://github.com/samcantrill/loom/pull/145
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root final v11 phase after Phase 8 merge; merge to `develop` after validation, automated review, and CI
- Workflow path: fast path, with local manager review because this fixes public operator wording and CLI behavior
- Successor dependency notes: none; this is the final v11 phase
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 8 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-14
- Refine pass: not needed; validation passed after a targeted pytest module-name fix
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Finalize the first-version queue operator contract by adding a thin CLI wrapper, queue preflight/status rendering helpers, deterministic CLI/service tests, and queue-owned docs that explain managed local and delegated SLURM operation without expanding queue policy.

## Full-Plan Context

Phases 5 through 8 created queue records, persistence, service/client/controller boundaries, managed local dispatch, and delegated SLURM dispatch. Phase 9 exposes those surfaces operationally and documents their ownership boundaries. Later work such as bulk CLI submission, retries, fairness, SSH, bundle transport, and richer scheduler policy must remain out of scope.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 8 merged into `develop`
- Why this base branch is correct: Phase 8 merge metadata is on `develop`, and this phase depends on its delegated SLURM adapter/status semantics
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge when no successor branch depends on it

## Source Phase Summary

- Goal: finalize queue status, cancel, daemon-service, foreground-drain operations, examples, preflight checks, and queue-owned documentation.
- Required scope: thin operational CLI for service lifecycle, foreground drain, status, and cancel; preflight diagnostics for queue service/config/authority/resources/SLURM/workspace assumptions; dedicated docs and cross-links; managed local and delegated SLURM examples; status rendering and operator diagnostics.
- Acceptance criteria: users can follow docs to operate managed local and delegated SLURM queues in deterministic or fakeable environments; CLI stays thin over Python service/client surfaces; preflight/status output explains authority, queue, and delegated scheduler ownership clearly.

## Current Source And Harness Findings

- `loom.cli.main` registers small command modules that own parser setup, handler logic, JSON envelopes, and text output.
- `loom.queue` already exposes `QueueService`, `QueueClient`, `QueueController`, config loading, status read models, managed resource reconciliation, local adapter, and delegated SLURM adapter.
- Queue service lifecycle is currently in-process only; the CLI should therefore open the configured SQLite-backed service, start it for the command, perform one operation, and exit instead of promising a hosted daemon supervisor.
- Existing docs under `docs/features/` use feature-specific pages plus cross-links from `cli.md`, `preflight.md`, `execution.md`, `runtime-resources.md`, and `slurm.md`.
- Existing default tests are deterministic; real SLURM behavior must stay out of default Phase 9 validation.

## In-Scope Work

- Add a `loom queue` CLI command group for `start`, `status`, `cancel`, and `drain-foreground`.
- Add queue preflight/read-model helpers for config reachability, repository reachability, authority configuration evidence, managed-pool reconciliation evidence when an authority store is supplied, delegated SLURM command availability, and delegated workspace-assumption diagnostics.
- Add queue status/cancel/drain text and JSON formatting that keeps queue state, authority evidence, and delegated scheduler evidence distinct.
- Add dedicated queue docs and examples, then cross-link them from execution, runtime resources, SLURM, preflight, and CLI docs.
- Add package, unit, integration, and e2e coverage for deterministic CLI/preflight/status/cancel/foreground-drain behavior.

## Out-of-Scope Work

- Bulk CLI submission or queue item creation as the primary public interface.
- A hosted queue daemon supervisor, process manager, or socket transport.
- Priorities, fairness, retries, cross-run dependencies, SSH, bundles, or remote artifact transport.
- Real SLURM requirements in default tests.
- Queue-side mutation of authority resource limits.

## Assumptions

- The first CLI is operational and repository-backed: each command loads an explicit queue config path and opens the configured repository through `QueueService.from_spec(...)`.
- `loom queue start` validates and reports the configured service/repository shape; it does not promise to leave a background process running.
- Queue preflight can report authority connection intent from CLI options and can run managed-pool reconciliation only when a caller supplies an authority coordination store to the Python helper.
- Delegated SLURM preflight can use command availability and launch-contract/workspace metadata checks as diagnostics without submitting scheduler work.

## Scope Contract

The CLI must remain a thin wrapper over existing queue service/client/controller APIs. It may load explicit queue config paths, open the configured repository, start the in-process service for the duration of a command, inspect/cancel items, and run foreground drain. It must not add enqueue semantics, scheduler policy, background process supervision, private authority storage access, or queue-side resource-limit mutation.

## Design Impact

- Maintainability: keeps operator formatting and preflight helpers small and colocated with queue ownership rather than spreading queue behavior across existing run CLI commands.
- Extensibility: text/JSON schemas can grow additively when later daemon transports, bundle proofs, or richer scheduler policies land.
- Domain neutrality: examples use generic managed resources and SLURM as the scheduler adapter, without research-domain assumptions.
- Source-tree boundaries: CLI imports public queue modules only; queue helpers may import public authority coordination/resource-admission and public SLURM command-runner APIs.

## Future Compatibility

The command group should leave room for a later hosted daemon transport by describing the current start command as an in-process service check. Preflight and status payloads should keep queue, authority, and delegated scheduler sections separate so later SSH, bundle, or policy fields can be added without rewriting existing operator output.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add CLI enqueue/bulk submit now | Phase 9 explicitly keeps the CLI operational and Python-first enqueue remains the control surface. |
| Build a queue supervisor daemon in the CLI | The existing queue service is in-process and no socket/process lifecycle contract exists in v11. |
| Fold queue docs into execution docs only | Queue ownership is top-level `loom.queue`; a dedicated feature doc prevents authority and queue truth from being collapsed. |
| Treat missing delegated proofs as success | The plan requires weaker delegated assumptions to be visible in preflight/status output. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| CLI commands are in-process repository operations, not a hosted daemon API | v11 has a Python-first service and no transport contract | A queue daemon/supervisor roadmap lands |
| CLI cannot enqueue runs | Bulk submission is out of scope and could define premature public run-intent syntax | Users need CLI-first queue submission |
| Managed-pool authority reconciliation in preflight needs injected store support for deterministic tests | Avoids private authority storage and hidden service discovery | A public queue daemon or authority discovery contract is added |

## Reviewability

- Expected PR size and shape: moderate CLI/preflight/status helpers, docs, and focused tests; no queue schema changes.
- Files and areas to inspect: `src/loom/cli/main.py`, new queue CLI/formatting helpers, queue preflight/status modules, docs cross-links, and CLI/integration/e2e tests.
- Scope-control checks: no enqueue command, no daemon supervisor, no private authority repository imports, no real SLURM default dependency, no resource-limit mutation.

## Implementation Steps

1. Add queue operational read/preflight helpers and formatter functions with unit coverage.
2. Add `loom queue` subcommands for start/status/cancel/drain-foreground and register them in the main parser.
3. Add deterministic integration/e2e CLI tests against SQLite-backed fake queue configurations.
4. Add dedicated queue docs, managed local and delegated SLURM examples, and feature-doc cross-links.
5. Run targeted queue CLI/preflight/status/docs tests, then the full PR gates.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py` or `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: CLI import smoke includes the queue command without making the queue root import private authority/server layers.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/queue/test_queue_preflight.py`, `tests/unit/loom/queue/test_queue_status.py`, `tests/unit/loom/cli/test_queue.py`, `tests/unit/loom/cli/test_main.py`
- Required assertions or deferral reason: queue preflight diagnostics, status rendering, cancel/status JSON payloads, and parser registration.

### Contract Suite

- Status: deferred
- Expected paths: not required
- Required assertions or deferral reason: Phase 9 adds CLI/docs wrappers over already-covered queue API contracts and no new durable queue schema.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/queue/test_cli_operations.py`
- Required assertions or deferral reason: CLI/service status, cancel, and foreground drain operate against deterministic SQLite queue state.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_queue_cli.py`
- Required assertions or deferral reason: `loom queue` smoke commands work in deterministic local environments.

### Opt-In Suites

- Status: deferred
- Markers affected: real SLURM smoke only
- Required assertions or deferral reason: delegated SLURM docs/preflight do not require real scheduler access by default.

## Risks

- Operator wording could imply queue state is authority truth; text and JSON must keep ownership sections separate.
- A `start` command could be mistaken for a persistent daemon; output must state the current in-process/config check behavior.
- Preflight must not reach private authority storage or mutate resource limits while checking managed pools.
- CLI commands must not accidentally add enqueue semantics or background scheduling loops.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/queue/test_queue_preflight.py tests/unit/loom/queue/test_queue_status.py tests/unit/loom/cli/test_queue.py tests/integration/queue/test_cli_operations.py tests/e2e/test_queue_cli.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: queue read/preflight helpers first, CLI module second, deterministic tests third, docs last.
- Tests to run with each slice: unit queue helper tests after helper edits; unit CLI tests after parser/handler edits; integration/e2e tests after CLI commands; docs link checks through existing validation gates.
- Decisions the executor must not revisit: no CLI enqueue, no daemon supervisor/process manager, no queue-owned authority limit mutation, no real SLURM dependency in default tests.
- Conditions that require stopping for the manager: needing a queue schema migration, new queue service transport contract, public scheduler policy redesign, or private authority storage import.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted and full PR gates passed after the local test module rename fix
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: added queue-owned preflight diagnostics, operator-facing queue status/cancellation read models, `loom queue` subcommands for preflight/start/status/cancel/drain-foreground, queue status/cancel/drain/preflight text and JSON formatting, deterministic CLI/integration/e2e coverage, import-boundary coverage, and dedicated queue docs with cross-links from CLI, execution, runtime resources, SLURM, and preflight docs.
- Implementation validation: focused Phase 9 pytest passed with 58 passed after renaming queue unit test modules to unique basenames; review-fix focused pytest passed with 7 passed; targeted Ruff passed; targeted Pyright passed with 0 errors; config-extra targeted queue tests passed with 8 passed; final-head `make validate-pr` passed with Ruff, Pyright, default harness 1434 passed/26 skipped/18 deselected, config-extra harness 438 passed/1471 deselected, and build; final-head `make test-summary` passed with package 77 passed/1 skipped, unit 1032 passed/7 skipped/1 deselected, contract 167 passed/2 skipped, integration 145 passed/8 skipped/13 deselected, e2e 41 passed/2 deselected, and config-extra 438 passed/1471 deselected.
- Refinement summary: no implementation refinement pass was needed. A validation blocker caused by duplicate pytest module basenames was fixed with a scoped test-file rename and phase-plan command update. Local manager review found one operator-UX issue where queue preflight treated the default authority config as explicit; fixed by only checking authority when authority flags are supplied, with regression coverage.
- Blocker-resolution summary: none.
- PR preparation: PR body prepared in `docs/roadmap/stage-11/phases/queue-ops-cli-docs-hardening-pr-body.md`; PR #145 opened against `develop`.
- Stack maintenance: none.
- Remaining blockers: none.
