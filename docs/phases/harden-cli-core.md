# Phase 6 Execution Plan: Hardening, Docs, And E2E Coverage

## Metadata

- Status: pr_open
- Feature focus: CLI Core
- PR title: `CLI Core - Phase 6: Hardening and E2E`
- Branch: `codex/harden-cli-core`
- Worktree: `/home/samcantrill/work/loom-worktrees/harden-cli-core`
- Phase execution plan path: `docs/phases/harden-cli-core.md`
- Full plan: `docs/implementation-plans/implementation-plan-v2.md`
- Source phase: Phase 6 - Hardening, Docs, And E2E Coverage
- Stack predecessor: none; Phases 1 through 5 are merged.
- Base branch: `develop` at `93aacbc` (`docs: record v2 phase 5 merged`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after local review, validation, and CI because the target is `develop`.
- Workflow path: fast path; this is final documentation and coverage over implemented behavior, with no new command design.
- Successor dependency notes: none; this is the final v2 phase.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v2.md`; no blocking findings remain.
- Plan quality gate loop budget: initial review used, plan refinement completed through v2 discussion, confirmation review not needed because no blocking findings remained.
- Draft pass: completed by the managing agent in this artifact.
- Refine pass: not needed on the fast path.
- Setup limitations: `git worktree add` required approved git metadata access after the sandbox could not create the branch ref. `origin/develop` was verified before branch creation.
- Blockers: none known.

## Objective

Finalize v2 CLI core by updating user-facing docs for the supported validate/plan/run surface and adding end-to-end coverage through `main(argv)` for the complete command set. The phase must not add new command behavior beyond small hardening fixes found by docs/e2e tests.

## Full-Plan Context

Phases 1 through 5 implemented run URI migration, shared CLI infrastructure, `loom validate`, `loom plan`, and `loom run`. This final phase makes the shipped surface reviewable and usable: docs should describe only the v2-supported commands, and e2e tests should exercise successful and failing command workflows.

Future roadmap commands remain deferred: status, logs, artifacts, stage workers, subprocess/SLURM/container executors, sweeps, catalogs, bundles, plugins, remote stores, and cleanup/reliability commands.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: all prior v2 phases are merged into `develop`.
- Retarget/rebase plan after predecessor merge: none expected.
- Branch cleanup constraints: delete this worktree and branch after merge if no successor branch depends on it.

## Source Phase Summary

- Goal: harden v2 behavior, document validate/plan/run, and add end-to-end coverage.
- Required scope: update README and CLI docs, add examples for validate/check-targets/plan/run/resume/selectors/text/JSON/explicit URI/default URI, document deferred commands, add e2e tests through `main(argv)` or the console entry point, and confirm import boundaries.
- Required checkpoints: strict local `file://` rules, `--check-targets` constructor warning, final import boundaries, and full validation gates.
- Acceptance criteria: docs describe supported v2 commands and deferred commands; e2e covers validate, check-targets, plan, run, failed run, dry-run, resume, explicit URI, default URI, and JSON output; `make validate-pr` and `make test-summary` pass.

## Current Source And Harness Findings

- `README.md` still presents v0 as local Python API first and says CLI is stub/import-safe.
- `docs/features/cli.md` still frames functional commands as post-v0 and lists many future commands under "Should Support Soon".
- Command behavior already has unit and config integration coverage; Phase 6 should add e2e coverage without duplicating every unit assertion.
- Existing `tests/e2e/test_local_pipeline_run.py` covers Python API execution. A separate CLI e2e file can use `main(argv)` and synthetic support stages.

## In-Scope Work

- Update README with concise v2 CLI quickstart and supported command examples.
- Update `docs/features/cli.md` to mark validate/plan/run as v2-supported and explicitly defer later commands.
- Document strict local run URI forms and rejected forms.
- Document that `validate --check-targets` imports and constructs trusted project targets.
- Add e2e tests through `main(argv)` for validate, validate `--check-targets`, plan, run, failed run, dry-run, resume, explicit run URI, default run URI, and JSON output.
- Add small hardening fixes only if e2e exposes a mismatch with the v2 plan.

## Out-of-Scope Work

- No new command groups or options.
- No status/log/artifact/stage/sweep/catalog/bundle/plugin/remote/container/reliability behavior.
- No broad runtime refactors or schema changes.
- No new dependency for docs or CLI rendering.

## Assumptions

- E2E coverage can use `main(argv)` rather than shelling out to the installed console script.
- Existing synthetic support stages are sufficient for successful, failed, and resume workflows.
- README can stay concise and link to `docs/features/cli.md` for detailed command behavior.

## Scope Contract

Documentation must state:

- Supported v2 commands are `loom validate`, `loom plan`, and `loom run`.
- `loom plan` is read-only and does not allocate or mutate run state.
- `loom run --dry-run` emits plan output and does not execute.
- Local run URIs must be explicit `file://` forms; plain paths and remote schemes are rejected in v2.
- `--check-targets` is the consent boundary for importing/constructing trusted `_target_` blocks.
- Later commands and executor/store families are deferred and unsupported in v2.

E2E tests must verify behavior, not merely help text.

## Design Impact

- Maintainability: docs and e2e tests lock the intended v2 CLI behavior without adding command complexity.
- Extensibility: deferred-command documentation leaves room for v3+ without overpromising current behavior.
- Domain neutrality: examples use synthetic generic stages only.
- Source-tree boundaries: no package boundary changes expected; import-boundary tests should remain green.

## Future Compatibility

- V3 diagnostics can extend the docs from the deferred-command list.
- V4+ runtime/executor options can update command docs without changing v2 examples.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Documentation-only final phase | V2 is the first functional CLI layer and needs e2e command coverage. |
| Add docs for all roadmap commands | It would overpromise unsupported behavior and obscure the v2 surface. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Examples use test support stages rather than a packaged demo stage | Loom remains domain-neutral and should not add project-specific sample stages in v2 | A future examples package or template feature is planned |

## Reviewability

- Expected PR size and shape: documentation updates, one e2e test file, possible small test helper updates, and phase artifacts.
- Files and areas to inspect: `README.md`, `docs/features/cli.md`, `tests/e2e/`, phase artifact, and any tiny hardening changes.
- Scope-control checks: no new command modules/options, no runtime/store algorithm changes, and no new dependencies.

## Implementation Steps

1. Add the phase plan commit.
2. Add CLI e2e tests covering the required v2 command workflows.
3. Update README and `docs/features/cli.md` to describe supported and deferred behavior.
4. Run targeted e2e/docs-adjacent tests plus import boundaries.
5. Run `make validate-pr` and `make test-summary`.
6. Prepare and merge the final phase PR.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: final CLI import/help boundaries remain safe after all command modules exist.

### Unit Suite

- Status: conditional.
- Expected paths: existing CLI unit tests if a hardening fix changes formatting/options.
- Required assertions or deferral reason: no new unit tests expected unless e2e exposes an edge case.

### Contract Suite

- Status: deferred.
- Expected paths: none expected.
- Required assertions or deferral reason: no new structural protocol in this phase.

### Integration Suite

- Status: required through final suite evidence.
- Expected paths: existing config CLI integration tests.
- Required assertions or deferral reason: validate/plan/run integration tests should continue passing.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_cli_core.py`.
- Required assertions or deferral reason: validate, check-targets, plan, run, failed run, dry-run, resume, explicit URI, default URI, and JSON output through `main(argv)`.

### Opt-In Suites

- Status: required for config-extra via final gates.
- Markers affected: `optional_dependency`.
- Required assertions or deferral reason: command e2e uses config composition and should skip cleanly when optional config deps are unavailable.

## Risks

- E2E tests may duplicate integration tests if not kept workflow-focused.
- README examples must avoid implying unsupported `status/logs/artifacts` behavior.
- Docs should be accurate about test support stage paths without presenting them as packaged user examples.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/e2e/test_cli_core.py tests/package/test_import_boundaries.py -q
uv run --extra config pytest tests/integration/config/test_cli_validate.py tests/integration/config/test_cli_plan.py tests/integration/config/test_cli_run.py -q
uv run ruff check .
uv run --extra config pyright
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: e2e tests first, docs second, hardening fixes only if tests reveal mismatches.
- Tests to run with each slice: run `tests/e2e/test_cli_core.py` after adding e2e tests and the config integration set after docs/hardening.
- Decisions the executor must not revisit: supported commands are validate/plan/run only; no remote stores or non-local executors in v2; no new dependencies.
- Conditions that require stopping for the manager: a docs/e2e requirement that cannot be satisfied without new command behavior or runtime refactors.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this commit.
- Final phase execution plan: completed in this commit; fast-path refine pass not needed.
- Implementation summary: added `tests/e2e/test_cli_core.py` covering validate, `--check-targets`, plan JSON, run JSON/text, failed run JSON, dry-run JSON, resume reuse, explicit/default run URIs, unsupported executor errors, and strict run URI rejection through `main(argv)`. Updated `README.md` and `docs/features/cli.md` to describe the supported v2 validate/plan/run surface, strict local `file://` run URI forms, the `--check-targets` consent boundary, JSON envelope behavior, and deferred command families.
- Implementation validation: targeted `uv run --extra config pytest tests/e2e/test_cli_core.py -q` passed with 7 tests; targeted default `uv run pytest tests/e2e/test_cli_core.py tests/package/test_import_boundaries.py -q` passed with 26 tests; targeted config integration `uv run --extra config pytest tests/integration/config/test_cli_validate.py tests/integration/config/test_cli_plan.py tests/integration/config/test_cli_run.py -q` passed with 15 tests; `uv run ruff check .` passed; `uv run --extra config pyright` passed with 0 errors. Final `make validate-pr` passed Ruff, Pyright, default 505 passed/12 skipped, config-extra 380 passed/519 deselected, and build. Final `make test-summary` passed package 43 passed/1 skipped, unit 417 passed/1 skipped, contract 36 passed/2 skipped, integration 9 passed/5 skipped, e2e 14 passed, and config-extra 380 passed/519 deselected.
- Refinement summary: no implementation refiner pass used; targeted validation and final gates passed after local assertion alignment in the e2e test.
- PR preparation: PR opened at `https://github.com/samcantrill/loom/pull/64`, targeting `develop` from `codex/harden-cli-core`; target verification passed with `baseRefName=develop`, `headRefName=codex/harden-cli-core`, and `state=OPEN`.
- Stack maintenance: not needed yet.
- Remaining blockers: none known.
