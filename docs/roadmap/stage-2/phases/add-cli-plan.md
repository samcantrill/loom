# Phase 4 Execution Plan: Plan Command

## Metadata

- Status: merged
- Feature focus: CLI Core
- PR title: `CLI Core - Phase 4: Plan Command`
- Branch: `codex/add-cli-plan`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-cli-plan`
- Phase execution plan path: `docs/roadmap/stage-2/phases/add-cli-plan.md`
- Full plan: `docs/roadmap/stage-2/implementation-plan.md`
- Source phase: Phase 4 - Plan Command
- Stack predecessor: none; Phases 1 through 3 are merged.
- Base branch: `develop` at `1940a51` (`docs: record v2 phase 3 merged`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after local review, validation, and CI because the target is `develop`.
- Workflow path: fast path; the v2 plan resolves the durable read-only planning and run URI decisions, and this phase adds one command plus narrow adapters.
- Successor dependency notes: Phase 5 will reuse the plan path for `loom run --dry-run` and must remain out of this phase.
- Plan quality gate: passed in `docs/roadmap/stage-2/implementation-plan.md`; no blocking findings remain.
- Plan quality gate loop budget: initial review used, plan refinement completed through v2 discussion, confirmation review not needed because no blocking findings remained.
- Draft pass: completed by the managing agent in this artifact.
- Refine pass: not needed on the fast path.
- Setup limitations: `git worktree add` required approved git metadata access after the sandbox could not create the branch ref. GitHub auth and `origin/develop` were verified before branch creation.
- PR: https://github.com/samcantrill/loom/pull/62
- PR body artifact: `docs/roadmap/stage-2/phases/add-cli-plan-pr-body.md`
- PR verification: `baseRefName=develop`, `headRefName=codex/add-cli-plan`, `state=OPEN`, CI check `checks` initially `IN_PROGRESS` and completed with `SUCCESS`.
- Merge: PR #62 squash-merged into `develop` as `de037446d512505d08a6b0b9b3408a4c36455659`.
- Blockers: none known.

## Objective

Add `loom plan` as a read-only CLI command over the existing config, pipeline, store, selector, resume, and explanation APIs. The command must preview stage decisions without executing stages, allocating default run URIs, creating run directories, acquiring locks, writing plans, or mutating prior run state.

## Full-Plan Context

Phases 1 through 3 have already migrated public run identity to `run_uri`, added shared CLI infrastructure, and implemented `loom validate`. Phase 4 consumes those surfaces to expose planning. Phase 5 will add mutating execution and default run URI allocation; Phase 6 will add final docs and e2e coverage.

Future-phase work that remains out of scope includes `loom run`, default URI allocation for execution, plan persistence, lock acquisition, status/log/artifact diagnostics, executor selection, remote stores, rich progress, and command docs beyond help text.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: all earlier v2 phases are merged and the local checkout matches `origin/develop`.
- Retarget/rebase plan after predecessor merge: none expected.
- Branch cleanup constraints: delete the phase branch and worktree after merge because no successor branch should depend on it while Codex-managed merges continue to land serially.

## Source Phase Summary

- Goal: add `loom plan` over v0 planning, selectors, strict resume, and explanations.
- Required scope: add `src/loom/cli/plan.py`, wire parser registration, map config/run URI/resume/selector options to owning APIs, format text and JSON plan views, and add narrow owning helpers only if CLI code would otherwise inspect private run layout.
- Required checkpoints: read-only fresh planning, explicit run URI validation, existing target failure for non-resume planning, strict resume requiring existing state, selector effects through planner APIs, stage explanation output, and no mutation.
- Acceptance criteria: fresh plan without `--run-uri` does not allocate a run URI; explicit new run URI remains read-only; existing URI without `--resume` fails; resume requires existing valid run state; selectors and `--explain` are reflected in planner output; no stage execution or run-state mutation occurs.

## Current Source And Harness Findings

- `src/loom/cli/main.py` currently registers `plan` as an unsupported placeholder and already provides shared config and selector option helpers.
- `src/loom/cli/options.py` already has `PlanCliOptions` and `SelectorCliOptions`; selector sets must be converted into `PlanSelectors` in deterministic stage order by planner APIs, not CLI logic.
- `src/loom/cli/results.py` and `src/loom/cli/formatting.py` contain placeholder plan result formatting that should be made useful for stage actions, reasons, selectors, summary, and optional explanation.
- `loom.pipeline.planning.plan_pipeline()` requires a concrete run URI and store pair. A fresh hypothetical `loom plan` without user `--run-uri` therefore needs an owning planning/store facade or sentinel URI owned outside the CLI.
- `LocalRunStore` owns local URI validation, path resolution, existence checks, and artifact roots. The CLI should ask the store/facade rather than converting URI strings to paths itself.
- Existing CLI tests use `main(argv)` and monkeypatch command-level helpers for orchestration coverage; integration tests can use synthetic support stages/configs already added for validate and execution suites.

## In-Scope Work

- Add `src/loom/cli/plan.py` and register it from `main.py`.
- Add a planning-owned facade if needed to support read-only CLI planning without CLI-local run layout handling.
- Compose config through `loom.config.compose_config` and validate/build the pipeline through public pipeline APIs.
- Convert CLI selectors into `PlanSelectors` while leaving graph-dependent validation in planner APIs.
- Validate explicit run URIs through store APIs and use resolved absolute `file:///...` values in output.
- For fresh plan without `--run-uri`, compute a hypothetical plan without allocating a default run URI or creating state.
- For explicit non-resume planning, fail if the run URI already exists.
- For resume planning, require `--run-uri`, open the run read-only, and compute strict resume decisions.
- Format concise text and stable JSON from a CLI-specific plan result view.
- Support `--explain STAGE` from structured explanation objects.

## Out-of-Scope Work

- No run execution, default run URI allocation, run creation, lock acquisition, plan persistence, status writes, or prior-state mutation.
- No `loom run --dry-run`; Phase 5 will delegate to the plan path.
- No CLI-local implementation of selector conflict rules, resume decisions, fingerprinting, artifact validation, or path derivation.
- No remote run URI support or compatibility with old `run_id` state.
- No docs/e2e expansion beyond tests needed for this command.

## Assumptions

- `LocalRunStore(root=Path("runs"))` is the acceptable default local store for planning because the store owns the default root behavior. Planning without `--run-uri` must still avoid allocation and writes.
- A hypothetical plan can use a non-persisted store-owned placeholder local run URI internally as long as user-facing result fields keep `run_uri` as `None`.
- Strict resume in v2 maps to `ResumeOptions(enabled=True)` against an existing opened run.
- Fresh non-resume planning maps to `ResumeOptions(enabled=False)` so the planner does not inspect prior stage state.

## Scope Contract

User-facing behavior:

- `loom plan CONFIG` prints ordered stage decisions and does not show or allocate a run URI.
- `loom plan CONFIG --run-uri file://...` prints the resolved absolute run URI if the target does not already exist.
- `loom plan CONFIG --run-uri file://... --resume` requires an existing valid run and computes resume-aware decisions.
- `loom plan CONFIG --resume` fails with a CLI usage-style operational error after parsing because resume has no run state address.
- `--explain STAGE` includes details for exactly that stage and fails clearly when the stage is absent from the plan.

JSON behavior:

- Use schema version `loom.cli.plan.v2`.
- The result payload is CLI-specific and includes config path, pipeline name, resolved run URI when user supplied one, resume flag, selectors, summary, ordered stage actions with reason codes/messages, and optional stage explanation.
- Do not emit raw persisted `ExecutionPlan.to_dict()` as the CLI JSON contract.

Error behavior:

- Config errors map to exit code 3, planning/pipeline/store run-state errors map to exit code 4 unless an existing shared type maps more specifically.
- JSON errors use the shared CLI error envelope after parsing succeeds.

## Design Impact

- Maintainability: command orchestration stays in `loom.cli`, while planning, selector validation, resume checks, URI resolution, and layout checks stay in owning packages.
- Extensibility: the CLI-specific plan view can grow in v3 diagnostics without exposing the persisted execution-plan schema as an automation contract.
- Domain neutrality: output describes stages, actions, reasons, and artifacts without project-specific semantics.
- Source-tree boundaries: CLI imports public config/pipeline/planning/store APIs only; no executors or project target modules are imported for planning.

## Future Compatibility

- Phase 5 can reuse the planning helper for `loom run --dry-run`.
- V3 status/preflight commands can reuse the JSON envelope, reason formatting, and plan view conventions.
- V4 runtime option models can replace CLI option dataclasses without changing `loom plan` flags.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Emit raw `ExecutionPlan.to_dict()` as JSON | It would couple CLI automation output to persisted/internal planner schema. |
| Allocate a default run URI for `loom plan` | Planning is read-only preview behavior; default allocation belongs to mutating `loom run`. |
| Let CLI inspect `Path` existence directly | Run layout and URI normalization belong to store/runtime APIs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| CLI plan JSON is a compact view and may omit advanced planner internals | V2 only needs stable automation output for core stage decisions | V3 diagnostics requires richer machine-readable explanations |

## Reviewability

- Expected PR size and shape: one command module, small registration/format/result updates, focused tests, and a narrow planning/store helper only if needed.
- Files and areas to inspect: `src/loom/cli/plan.py`, `src/loom/cli/main.py`, `src/loom/cli/results.py`, `src/loom/cli/formatting.py`, any new owning planning/store facade, and CLI plan tests.
- Scope-control checks: no executor import/use, no stage target instantiation, no run directory creation in plan, no default run URI allocation, no direct CLI path splitting, and no raw execution-plan JSON contract.

## Implementation Steps

1. Add the phase plan commit, then add any minimal owning planning/store facade needed for read-only CLI planning.
2. Implement `loom.cli.plan` registration, orchestration, selector/run URI adapters, and explanation handling.
3. Extend CLI result and formatting helpers for useful plan text/JSON.
4. Add unit coverage for command orchestration, formatting, resume/run URI errors, selector mapping, and explanation payloads.
5. Add integration coverage with real config composition, fresh planning, explicit run URI, existing target failure, resume planning, and selector/explain behavior.
6. Run targeted suites, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: importing/helping the plan command must not load executors, optional backends, or project targets.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/cli/test_plan.py`, `tests/unit/loom/cli/test_formatting.py`, `tests/unit/loom/cli/test_main.py`, `tests/unit/loom/cli/test_options.py`, plus owning facade unit tests if introduced.
- Required assertions or deferral reason: parser registration, option preservation, run URI and resume rules, no-allocation behavior, selector adapter behavior, text/JSON formatting, explanation selection, and shared JSON errors.

### Contract Suite

- Status: deferred unless a new public protocol is introduced.
- Expected paths: none expected.
- Required assertions or deferral reason: Phase 4 should use existing store/planner protocols rather than adding a new structural contract.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_cli_plan.py`.
- Required assertions or deferral reason: real config composition plus planner behavior for fresh plan, explicit new run URI, existing target failure, strict resume against valid state, selectors, and explain output.

### E2E Suite

- Status: deferred.
- Expected paths: Phase 6 e2e suite.
- Required assertions or deferral reason: the implementation plan assigns broad command e2e coverage to Phase 6.

### Opt-In Suites

- Status: not affected beyond existing config-extra integration tests.
- Markers affected: `optional_dependency` for config composition integration tests.
- Required assertions or deferral reason: no external services or optional executor backends are involved.

## Risks

- `plan_pipeline()` currently needs stores and a run URI even for fresh planning; the implementation must avoid leaking any internal placeholder URI into user-facing output.
- Existing-target checks must remain store-owned and must not turn into path parsing in `loom.cli`.
- Resume planning should fail loudly for invalid or missing run state, while missing individual stage state inside a valid run remains a planner decision.
- Explanation output must be useful without exposing raw persisted schema as the whole CLI contract.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/cli tests/package/test_import_boundaries.py -q
uv run --extra config pytest tests/integration/config/test_cli_plan.py -q
uv run ruff check .
uv run --extra config pyright
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: facade first if needed, command orchestration second, formatting/results third, tests last.
- Tests to run with each slice: start with `tests/unit/loom/cli/test_plan.py`, then add the config-extra integration test, then run the targeted command list above.
- Decisions the executor must not revisit: plan is read-only, no default run URI allocation, strict resume requires explicit run URI, non-resume explicit existing URI fails, JSON is a CLI-specific view, and selector/resume logic belongs outside CLI.
- Conditions that require stopping for the manager: a need to create or mutate run state for fresh planning, a need to import executors/project targets, or missing owning APIs that cannot be filled without changing Phase 5 execution behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this commit.
- Final phase execution plan: completed in this commit; fast-path refine pass not needed.
- Implementation summary: completed in `5fd9d00` (`feat: implement plan command`). The phase adds `loom plan`, CLI-specific plan result output, read-only fresh planning, explicit run URI validation/existence checks through the local store, strict resume planning, selector forwarding, explanation payloads, and import-boundary coverage. `LocalRunStore` now owns its default root and exposes `run_uri_exists()` for non-resume read-only existence checks.
- Implementation validation: targeted `uv run pytest tests/unit/loom/cli tests/package/test_import_boundaries.py -q` passed with 48 tests; targeted `uv run --extra config pytest tests/integration/config/test_cli_plan.py -q` passed with 5 tests; `uv run ruff check .` passed; `uv run --extra config pyright` passed with 0 errors; `make validate-pr` passed with default 497 passed / 11 skipped and config-extra 373 passed / 504 deselected plus build success; `make test-summary` passed with package 42 passed / 1 skipped, unit 410 passed / 1 skipped, contract 36 passed / 2 skipped, integration 9 passed / 5 skipped, e2e 7 passed, and config-extra 373 passed / 504 deselected.
- Refinement summary: not needed; targeted and full validation passed without a phase-refiner pass.
- PR preparation: completed in `822ef87`; PR opened and verified against `develop` as https://github.com/samcantrill/loom/pull/62.
- Stack maintenance: not needed; no successor branch depended on `codex/add-cli-plan` when it merged.
- Remaining blockers: none known.
