# Phase 9 Execution Plan: Supervisor Lifecycle Commands

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 9: Supervisor Lifecycle Commands`
- Branch: `codex/authority-supervisor-lifecycle`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-supervisor-lifecycle`
- Phase execution plan path: `docs/roadmap/stage-10/phases/authority-supervisor-lifecycle.md`
- Full plan: `docs/roadmap/stage-10/implementation-plan.md`
- Source phase: Phase 9 - Supervisor Lifecycle Commands
- Stack predecessor: none; Phase 8 merged in PR #126 and is recorded in the plan
- Base branch: `develop` at `7164edf`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 10 adopts strict resolver/factory use of the registry records this phase writes.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/roadmap/stage-10/implementation-plan.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: branch and worktree were created from local `develop` at `7164edf`, after Phase 8 merge metadata was pushed
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Add explicit local authority supervisor lifecycle commands that initialize a repository-backed FastAPI authority service, record workspace-local registry facts after readiness, and report process, repository, readiness, registry, and generation diagnostics without starting hidden supervisors from runtime mutation paths.

## Full-Plan Context

Phase 8 added registry records and validation but did not populate them from normal commands. Phase 9 makes the local authority service operational through explicit CLI lifecycle commands. Phase 10 owns resolver and runtime adoption, so this phase may write registry records and expose lifecycle diagnostics but must not make `loom run`, factories, or resolver paths auto-start or auto-adopt the supervisor.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 8 merged to `develop` in PR #126
- Why this base branch is correct: the implementation plan records Phase 8 merged, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: implement explicit local authority supervisor lifecycle commands and generation handling.
- Required scope: `loom authority start`, `status`, `doctor`, `stop`, and `restart`; explicit service state directory; repository-backed FastAPI service startup; registry writes after readiness; health/readiness checks; restart generation changes or stale-client invalidation.
- Required checkpoints: no workspace-local default service state directory, no hidden runtime startup, incompatible repository state is not overwritten, diagnostics include selected state directory, and registry generation mismatches are visible.
- Acceptance criteria: users can start/inspect/stop/restart a local supervisor, status/doctor distinguish process/readiness/repository/registry/generation facts, and lifecycle commands leave runtime mutation paths unchanged.

## Current Source And Harness Findings

- `src/loom/cli/main.py` does not yet register an `authority` command; `src/loom/cli/authority.py` currently only contains shared authority option helpers and can own the subcommand tree with lazy imports.
- `src/loom/authority/app.py` can construct the FastAPI app from injected services, and `src/loom/authority/services.py` can bind a private repository through `repository_authority_services`.
- `src/loom/authority/_repository.py` initializes and reads private repository identity. Existing initialization preserves service generation for an existing DB, so restart needs a bounded private generation-rotation helper or equivalent stale-client invalidation behavior.
- `src/loom/pipeline/stores/authority_registry.py` provides the workspace-local registry write/read/validation surface and should be used rather than hand-written JSON.
- The project has a runtime FastAPI dependency but no ASGI server dependency. Starting a local FastAPI process requires adding a small ASGI server dependency, preferably `uvicorn`, with the design reason recorded here and in the PR body.
- Package import-boundary tests already forbid eager FastAPI/server imports from low-level modules. CLI command registration must keep server imports inside handlers or supervisor implementation modules.

## In-Scope Work

- Register `loom authority` with `start`, `status`, `doctor`, `stop`, and `restart` subcommands.
- Add a private supervisor implementation module under `loom.authority` for state-file handling, process launch/termination, readiness polling, repository identity checks, generation rotation on restart, registry writes, and diagnostic result models.
- Add a small process entrypoint for the repository-backed FastAPI app and use an ASGI server to serve it locally.
- Require `--state-dir` for `start` and `restart`. Allow `status`, `doctor`, and `stop` to resolve state from `--state-dir` or from the workspace registry when available.
- Write registry records only after readiness succeeds, including endpoint, state directory, workspace identity, service generation, protocol/version/capability facts, timestamps, and health state.
- Report structured JSON and concise text outputs through existing CLI formatting/result patterns.
- Add package, unit, contract, integration, and minimal e2e coverage for command registration, state-dir validation, lifecycle planning, registry writes, diagnostics, readiness mapping, and deterministic CLI smoke behavior.

## Out-of-Scope Work

- Runtime resolver/factory adoption, `loom run` startup behavior, and automatic supervisor discovery.
- Workspace coordination service API, resource admission, user-global discovery, hosted process managers, and offline import.
- Long-running daemon supervision beyond local PID/state-file lifecycle.
- Multi-host process management, TLS, authentication, and remote deployment.

## Assumptions

- Adding `uvicorn` as a runtime dependency is justified because FastAPI does not provide an ASGI server and Phase 9 explicitly requires a startable FastAPI authority service.
- A local endpoint default of `127.0.0.1` with an explicit or default port is sufficient for v10 local supervisor semantics. Tests should pass an available port to avoid collisions.
- Workspace ID can default to a deterministic local workspace-root identifier until a later global discovery/identity phase introduces richer workspace identities.
- Stop can mark the registry record unavailable when the current record points at the stopped state directory, but it must not delete registry history silently.

## Scope Contract

The lifecycle surface is explicit and local. `start` and `restart` must fail unless the service state directory is supplied by the user. Lifecycle commands may initialize or mutate the private authority repository and `.loom/authority/` registry, but ordinary runtime store creation and resolver paths must not start, stop, restart, or auto-adopt a supervisor.

Supervisor state files are operational metadata, not public protocol. Registry records remain the public discovery artifact. If process state and registry facts disagree, `doctor` must report the mismatch and fail closed rather than rewriting unrelated state.

## Design Impact

- Maintainability: keeps process supervision, readiness polling, and registry publication in one authority-owned module instead of scattering CLI subprocess details through command handlers.
- Extensibility: command/result shapes leave room for hosted managers and user-global discovery later without changing registry records from Phase 8.
- Domain neutrality: lifecycle diagnostics describe generic authority service facts only.
- Source-tree boundaries: CLI handlers call authority supervisor helpers lazily; pipeline stores remain independent from FastAPI, subprocess, and private repository imports.

## Future Compatibility

The local supervisor should be a stepping stone toward strict online mutation policy in Phase 10. Registry records must contain enough endpoint/generation/state facts for Phase 10 to reject stale clients without triggering hidden startup. Hosted managers can later replace the local process launcher while preserving CLI result shapes and registry writes.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Auto-start the supervisor from runtime factory or resolver paths | The v10 plan explicitly rejects hidden supervisors and assigns runtime adoption to Phase 10. |
| Implement lifecycle as registry-only stubs | Acceptance requires users to start and inspect a local authority supervisor. |
| Add a workspace-local default service state directory | Phase 9 requires explicit service state selection to avoid surprising DB placement. |
| Persist only PID health without readiness/version checks | Status and doctor must distinguish process health, service readiness, repository schema, registry state, and generation mismatch. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local supervisor is single-host and PID-file based | v10 needs explicit local lifecycle before hosted managers. | Hosted service manager or multi-host supervisor support begins. |
| Default workspace ID is derived locally | User-global discovery and richer workspace identity are later phases. | Phase 10+ needs cross-workspace or shared-service identity. |
| Uvicorn becomes a runtime dependency | FastAPI service startup needs an ASGI server. | The project adopts a different built-in server strategy. |

## Reviewability

- Expected PR size and shape: one authority supervisor module, one service entrypoint, CLI subcommand registration, dependency/lock update, tests, and phase docs/PR body.
- Files and areas to inspect: `src/loom/authority/supervisor.py`, the FastAPI service entrypoint, `src/loom/cli/authority.py`, `src/loom/cli/main.py`, repository generation rotation, registry writes, and CLI tests.
- Scope-control checks: no runtime factory/resolver adoption, no hidden startup from `loom run`, no user-global discovery, no coordination/resource/offline import work, and no low-level package eager imports of FastAPI/server modules.

## Implementation Steps

1. Add supervisor data models, state-file helpers, repository identity/generation handling, readiness polling, and registry publication.
2. Add a repository-backed FastAPI process entrypoint and the minimal ASGI server dependency needed to run it.
3. Register `loom authority` subcommands with text/JSON result formatting and lazy supervisor imports.
4. Add package, unit, contract, integration, and e2e coverage for explicit state-dir validation, registry updates, diagnostics, and command smoke behavior.
5. Run targeted validation, full PR gates, prepare the PR body, and open the Phase 9 PR.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: importing `loom`, `loom.pipeline.stores`, and command helper modules does not eagerly import FastAPI/server/private repository layers beyond the explicitly tested authority CLI command module behavior.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/authority/test_supervisor.py`, new or updated `tests/unit/loom/cli/test_authority.py`
- Required assertions or deferral reason: state-dir requirement, supervisor state parsing, restart generation rotation, registry publication payloads, stale/missing process diagnostics, JSON/text output formatting, and command registration.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_fastapi_skeleton_contract.py` or new authority supervisor contract coverage
- Required assertions or deferral reason: supervisor readiness and version facts map to existing authority protocol readiness/capability models and registry fields.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/authority/test_supervisor_lifecycle.py`
- Required assertions or deferral reason: start helper initializes repository state, writes registry after readiness, status/doctor distinguish registry/generation mismatches, and stop marks the local service unavailable.

### E2E Suite

- Status: required
- Expected paths: new `tests/e2e/test_authority_supervisor_cli.py`
- Required assertions or deferral reason: minimal CLI smoke using a free local port can start, status, doctor, stop, and verify registry output. If process startup is unstable in the sandbox, local evidence must record the reason and CI must still run it.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no external service, scheduler, network beyond local loopback, or long-running soak test is required.

## Risks

- Process cleanup must be reliable enough not to leave orphan local servers during tests or repeated user commands.
- Restart generation rotation must not corrupt existing repository state or silently make stale registry clients look valid.
- Adding `uvicorn` changes runtime dependency footprint and must stay limited to serving the already-required FastAPI authority app.
- Local socket tests can fail under sandbox restrictions; run them with the same escalation pattern used by prior authority phases when needed.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/authority src/loom/cli/authority.py src/loom/cli/main.py tests/package/test_import_boundaries.py tests/unit/loom/authority/test_supervisor.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority/test_supervisor_lifecycle.py tests/e2e/test_authority_supervisor_cli.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority src/loom/cli/authority.py tests/unit/loom/authority/test_supervisor.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority/test_supervisor_lifecycle.py tests/e2e/test_authority_supervisor_cli.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/unit/loom/authority/test_supervisor.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority/test_supervisor_lifecycle.py tests/e2e/test_authority_supervisor_cli.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: supervisor models/state helpers, process entrypoint/dependency, CLI command registration, registry/status/doctor behavior, then tests and docs.
- Tests to run with each slice: unit supervisor tests after models, CLI tests after command registration, integration/e2e tests after process launch, package tests after import changes.
- Decisions the executor must not revisit: no hidden runtime startup, no workspace-local default state dir for start/restart, no resolver/factory adoption, no user-global discovery, and no coordination/resource/offline import work.
- Conditions that require stopping for the manager: unable to add a bounded ASGI server dependency, need to change public registry record shape from Phase 8, or inability to make process cleanup deterministic.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted validation and full PR gates passed after implementation
- PR review: used by managing agent on 2026-05-11; one startup-exit edge case was found and fixed
- Blocker resolution: 1/3 used for the startup-exit readiness guard and unit regression

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary: added an explicit `loom authority` lifecycle command group with `start`, `status`, `doctor`, `stop`, and `restart`; added authority-owned supervisor process/state/registry helpers; added a private FastAPI server entrypoint backed by the authority repository; added generation rotation on restart; added `uvicorn` as the bounded ASGI server dependency needed to run the existing FastAPI app; and covered package boundaries, unit helpers, contract readiness-to-registry compatibility, integration process lifecycle, and e2e CLI lifecycle smoke behavior.
- Implementation validation: targeted Ruff passed; targeted Pyright passed; targeted pytest passed with 54 selected phase tests during implementation, and the final review-fix supervisor unit run passed with 7 tests. `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed with Ruff clean, Pyright clean, default pytest 1285 passed / 18 skipped / 14 deselected, config-extra 420 passed / 1314 deselected, and build success. `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 68 passed / 1 skipped, unit 931 passed / 1 skipped, contract 146 passed / 2 skipped, integration 126 passed / 8 skipped / 10 deselected, e2e 40 passed / 1 deselected, and config-extra 420 passed / 1314 deselected.
- Refinement summary: no separate refiner pass was needed; one implementation-pass cleanup ensured failed state/registry publication terminates a started server.
- Blocker-resolution summary: used one scoped pass to make startup fail immediately if the child process exits before readiness and to add a unit regression.
- PR preparation: PR body drafted in `docs/roadmap/stage-10/phases/authority-supervisor-lifecycle-pr-body.md`; PR opened as https://github.com/samcantrill/loom/pull/127.
- Stack maintenance:
- Remaining blockers: none.
