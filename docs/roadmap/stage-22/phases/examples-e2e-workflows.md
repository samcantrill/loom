# Phase 3 Execution Plan: End-To-End Workflow Behavior

## Metadata

- Status: final phase execution plan
- Feature focus: Examples And Validation
- PR title: `Examples And Validation - Phase 3: E2E Workflows`
- Branch: `codex/examples-e2e-workflows`
- Worktree: `/home/samcantrill/work/loom-worktrees/examples-e2e-workflows`
- Phase execution plan path: `docs/roadmap/stage-22/phases/examples-e2e-workflows.md`
- Full plan: `docs/roadmap/stage-22/implementation-plan.md`
- Source phase: Phase 3, "End-To-End Workflow Behavior"
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR; merge-eligible after automated review, required validation, CI, and target-branch checks pass against `develop`
- Workflow path: fast path
- Successor dependency notes: Phase 4 should branch from updated `develop` after this phase merges, or from `codex/examples-e2e-workflows` only if this phase is validated and open but not yet mergeable.
- Plan quality gate: passed on 2026-05-18 in `docs/roadmap/stage-22/implementation-plan.md`
- Plan quality gate loop budget: already consumed and passed before this phase plan; no further plan-review pass requested
- Draft pass: completed in this artifact
- Refine pass: not needed on fast path; scope remains docs/examples/tests-only, no public contract is being designed, and no blockers are recorded
- Setup limitations: worktree was created from local `origin/develop` at `341e9d5` (`docs: record stage 22 phase 2 merge`); the first sandboxed worktree creation could not write Git refs, and the approved escalated rerun succeeded
- Blockers: environment constraints blocked full execution of targeted suites in this sandbox

## Objective

Add representative end-to-end evidence for public CLI and Python example journeys so Stage 22 proves complete user workflows, not only manifest consistency, smoke scripts, and targeted integration behavior. The phase should connect selected examples and docs claims to stable e2e validation while keeping all checks local, synthetic, fake-backed, and free of runtime behavior changes.

## Full-Plan Context

Stage 22 is a confidence and usability stage for implemented behavior. Phase 1 merged the example manifest and catalog contract. Phase 2 merged focused integration evidence for runnable `full` examples. Phase 3 now owns representative e2e journeys across authoring, execution, operations, diagnostics, export/import, events, cleanup/retention where current public surfaces support them. Phase 4 remains responsible for final docs audit, final evidence rollup, and implementation-plan completion metadata, so broad stale-text cleanup and final roadmap bookkeeping stay out of scope here.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 2 merged into `develop` through PR #197, merge commit `91c1585e849f662417acdc11ae22dc2b1806c500`, and merge metadata is present on `origin/develop` at `341e9d5`; Phase 3 has no unmerged predecessor.
- Retarget/rebase plan after predecessor merge: none for this phase because it targets `develop` directly.
- Branch cleanup constraints: do not delete this branch until any Phase 4 successor is rebased or retargeted away from it if stacked continuation becomes necessary.

## Source Phase Summary

- Goal: cover representative CLI and Python user journeys with e2e or equivalent workflow tests.
- Required scope: e2e tests for public example workflows, CLI/Python example READMEs where command flows are documented, and focused feature docs that describe example-backed journeys.
- Required checkpoints: selected journeys run through public CLI or Python APIs, assert stable user-visible results, include at least one natural failure or diagnostic path, preserve explicit suite placement, and keep manual external-system boundaries truthful.
- Acceptance criteria: targeted e2e and CLI workflow checks pass; docs and manifests name truthful validation paths for examples that gain e2e evidence; no real network, cluster, daemon, provider SDK, credential, or runtime behavior change is introduced.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `examples/README.md`, `examples/authoring/README.md`, `examples/execution/README.md`, and `examples/operations/README.md` define the current user-facing CLI and Python workflow catalog.
  - Phase 1 manifest fields now include `public_surfaces`, `owner_docs`, `owner_stages`, `validation_path`, optional `validation_command`, and manual rationale.
  - Phase 2 added `tests/integration/examples/test_example_workflows.py` for `operations.captured-logs`, `operations.failing-run`, `operations.resource-preflight`, `operations.resource-leases`, and `operations.offline-import-rejections`.
  - Focused coverage docs exist for configuration, authority, SLURM, and containers under `docs/features/*-example-coverage.md`.
- Existing tests or harness behavior:
  - `tests/integration/docs/test_v0_python_examples.py` validates manifest/catalog consistency and smoke example execution.
  - Current e2e coverage includes public CLI and Python workflows in `tests/e2e/test_config_composition_public_api.py`, `tests/e2e/test_local_pipeline_run.py`, `tests/e2e/test_cli_core.py`, `tests/e2e/test_cli_runs_e2e.py`, `tests/e2e/test_cleanup_cli.py`, `tests/e2e/test_cli_slurm_dry_run.py`, and related CLI suites.
  - Existing e2e tests already prove many underlying journeys, but example metadata and README claims do not yet clearly identify representative e2e evidence for selected public examples.
- Import-boundary or dependency constraints:
  - Core runtime modules must not import examples or docs validation tooling.
  - E2E tests must stay local and deterministic by default, using `tmp_path`, fake/local backends, public `main(argv)` calls, public Python APIs, and existing optional dependency markers where appropriate.
  - No test may require a real Docker daemon, Apptainer installation, SLURM scheduler, network, hosted authority, provider SDK, credentials, or persistent generated state.

## In-Scope Work

- Select a small representative set of end-to-end journeys from existing public examples and current e2e coverage, favoring authoring/config composition, local execution/resume, CLI diagnostics/failure handling, runs export/import, cleanup/retention, events/lock lifecycle, and SLURM dry-run where already fake/local-backed.
- Add or extend targeted e2e tests that exercise those journeys through public CLI commands or public Python APIs and assert stable user-visible results, persisted records, generated artifacts, events, diagnostics, or cleanup effects.
- Update example manifests, group READMEs, and focused feature coverage docs only where needed to point selected workflows at named e2e validation paths or to clarify that integration/smoke evidence remains the correct tier.
- Keep manual examples manual and ensure real external-system flows stay excluded from default validation with explicit rationale.
- Reuse existing e2e helpers and public test patterns where practical; add only small test-owned helpers if they improve reviewability without creating docs/runtime coupling.

## Out-of-Scope Work

- Runtime behavior, CLI behavior, executor/store/authority/plugin behavior, cleanup/retention behavior, or public API changes.
- Real external-system e2e validation in the default suite, including Docker daemons, Apptainer, SLURM clusters, network services, hosted backends, provider SDKs, or credentials.
- Broad option-matrix testing that duplicates unit, contract, or integration suites.
- Adding new domain-specific tutorial projects or examples that depend on downstream project code.
- Phase 4 final documentation audit, final suite-evidence rollup, implementation-plan completion metadata, or broad README/feature-doc cleanup unrelated to Phase 3 e2e evidence.

## Assumptions

- Representative e2e coverage can be selected from implemented public surfaces without adding product behavior.
- It is acceptable for some examples to keep smoke or integration validation paths when e2e coverage would duplicate lower-level evidence or require external systems.
- Existing e2e tests may be extended or cross-referenced rather than replaced, provided validation paths are durable and reviewable.
- Stable summaries and structured payload assertions are preferable to brittle golden-output comparisons.

## Scope Contract

No runtime public contract changes are in scope. The phase may affect only tests, examples, manifests, and documentation claims:

- User-facing examples must keep using public Python APIs or supported CLI commands.
- E2E workflows must write to temporary or redirected roots and must not depend on generated state from earlier runs.
- Validation paths in manifests and docs must point to named tests that prove the stated journey, not merely import modules or assert fixture setup.
- Failure or diagnostic coverage should use stable public codes, statuses, structured JSON fields, or durable file existence checks.
- Manual external-system examples remain `validation: manual`; fake/local dry-run evidence must not be described as proof of live scheduler or daemon behavior.
- Any need to touch `src/loom` for example validation is a stop condition unless the manager explicitly reassigns the phase.

## Design Impact

- Maintainability: named e2e validation paths make it easier to review whether user-facing examples still match complete workflows.
- Extensibility: representative tests leave room for future example groups without making every example part of the slowest suite.
- Domain neutrality: examples and tests continue to use synthetic pipelines, generic resources, local stores, and fake backends.
- Source-tree boundaries: expected changes stay in `tests/e2e/`, `examples/`, focused `docs/features/`, and possibly docs integration metadata; `src/loom` should remain untouched.

## Future Compatibility

Phase 3 should leave Phase 4 with a clear set of validated user journeys and a short list of intentionally manual or lower-tier examples. If e2e coverage reveals that docs overpromise unsupported behavior, the correct action is to narrow the docs or mark the workflow manual, not to implement runtime behavior. If default e2e runtime cost grows too much, use existing markers or representative selection instead of moving external systems into the default gate.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add e2e coverage for every example manifest | Too slow and duplicative; the implementation plan calls for representative user journeys, not exhaustive permutations. |
| Convert Phase 2 integration tests into e2e tests | Blurs the integration/e2e boundary and would retest lower-level example behavior instead of complete user journeys. |
| Validate live Docker, Apptainer, SLURM, or hosted authority flows | Violates Stage 22 default-local validation and external-system constraints. |
| Change runtime code to make a desired e2e workflow pass | Stage 22 demonstrates implemented behavior; missing behavior must become manual/no-example documentation. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| E2E coverage remains representative rather than per-example exhaustive | Keeps default validation focused and avoids duplicating lower-level suites | Regressions repeatedly escape through untested end-to-end paths or users rely on an uncovered example as a primary onboarding path. |
| Some examples may retain smoke or integration validation paths after this phase | Those tiers remain the right evidence when e2e coverage would add little or require external systems | Phase 4 finds a runnable example whose documented claims are stronger than its validation evidence. |
| Stable summary assertions may not cover every detail of generated files | Reduces brittleness while proving public results and durable artifacts | Output or artifact regressions escape because assertions are too weak. |

## Reviewability

- Expected PR size and shape: a focused tests/examples/docs PR with targeted e2e additions or updates, manifest validation-path updates for selected examples, and narrow README or feature-doc edits.
- Files and areas to inspect: `tests/e2e/`, `examples/**/example.yaml`, example group READMEs, focused `docs/features/*-example-coverage.md`, and any touched docs/example validation tests.
- Scope-control checks: no `src/loom` changes, no new runtime dependencies, no broad docs audit, no real external-system requirements, no domain-specific examples, and no Phase 4 completion metadata.

## Implementation Steps

1. Inventory current e2e modules and example manifests, then choose the smallest set of representative workflows that complements Phase 2 integration evidence.
2. Add or extend targeted e2e tests for selected CLI/Python journeys using temporary roots, fake/local backends, and stable structured assertions.
3. Update selected manifests, group READMEs, and focused coverage docs to name the e2e evidence where it is now the clearest validation path.
4. Preserve manual classifications and add clarification only where docs could otherwise imply live external-system validation.
5. Run targeted e2e and docs/example checks before leaving final PR-gate evidence to PR preparation.

## Test Plan

### Package Suite

- Status: required as final regression gate; no new package tests expected
- Expected paths: existing `tests/package/` through `make validate-pr`
- Required assertions or deferral reason: public package imports used by the examples and e2e tests must keep working. Adding package tests or touching package metadata should be treated as scope drift unless needed to fix an uncovered existing packaging regression.

### Unit Suite

- Status: deferred for new coverage; existing unit suite required through final gate
- Expected paths: none unless a reusable test-owned helper is introduced, then the nearest existing test-helper unit location
- Required assertions or deferral reason: Phase 3 validates user journeys, not isolated runtime units. If helper logic becomes nontrivial, cover parsing/error reporting without importing docs tooling into runtime modules.

### Contract Suite

- Status: deferred for new coverage; existing contract suite required through final gate
- Expected paths: none
- Required assertions or deferral reason: this phase does not define runtime extension-point contracts or schema changes. New contract tests would indicate scope drift unless an existing contract assertion needs a small update to preserve current behavior.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/docs/test_v0_python_examples.py` and `tests/integration/examples/test_example_workflows.py`
- Required assertions or deferral reason: manifest/catalog validation and Phase 2 example-workflow integration evidence must keep passing after any validation-path, README, or manifest edits.

### E2E Suite

- Status: required
- Expected paths: selected `tests/e2e/` modules, likely including existing coverage around config composition, local pipeline run/resume, CLI diagnostics, runs export/import, cleanup, and SLURM dry-run; add a new focused module only if it makes example-backed workflow evidence clearer.
- Required assertions or deferral reason: representative journeys must run through public CLI or Python APIs, assert stable user-visible results, include at least one natural failure or diagnostic path, and avoid real external systems.

### Opt-In Suites

- Status: deferred
- Markers affected: real Docker, Apptainer, SLURM, network, provider, and hosted-service checks remain manual or opt-in
- Required assertions or deferral reason: Stage 22 Phase 3 default validation must not require external daemons, clusters, services, credentials, or provider SDKs. Fake/local and dry-run behavior may be covered in default e2e tests.

## Risks

- E2E additions can become slow or flaky if they cover broad option matrices instead of representative journeys.
- Example validation paths can become overly specific to incidental test names or output formatting.
- Docs updates can drift into Phase 4 final-audit scope.
- A desired user journey may reveal missing runtime behavior; that must become a manual/no-example boundary rather than implementation work.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/e2e
uv run pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py
make test-e2e
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: e2e inventory and representative journey selection; targeted e2e additions or updates; manifest and README validation-path updates; focused feature-doc clarifications for e2e evidence and manual boundaries.
- Tests to run with each slice: run the affected `tests/e2e/...` module after e2e edits; run docs/example integration checks after manifest or README changes; run `make test-e2e` before PR preparation if feasible.
- Decisions the executor must not revisit: no runtime behavior, no external-system default validation, no domain-specific examples, no replacement of manifest metadata, no broad Phase 4 docs audit, and no exhaustive e2e matrix.
- Conditions that require stopping for the manager: an e2e journey needs `src/loom` changes, a default check needs real network/daemon/cluster/provider access, validation cannot be isolated in temporary roots, or the work would need Phase 4 final metadata/audit changes.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; reserved for later workflow stages only if targeted validation fails, suite coverage is missing, or a concrete implementation blocker appears
- PR review: unused; reserved for the later automated PR review gate
- Blocker resolution: 1/3 used

## Completion Notes

- Draft plan: completed on fast path in this artifact
- Final phase execution plan: completed on fast path; refine pass not needed
- Implementation summary: Added representative public-journey e2e coverage in
  `tests/e2e/test_example_journeys.py` for local resume, authority lifecycle
  CLI, SLURM dry-runs, and Docker executor success plus failure diagnostics;
  repointed manifests to those e2e paths and updated group/feature docs to
  call out representative evidence. The local execution example was also
  hardened to use the local SQLite authority store and the public
  `StageContext.load_input` helper so the documented local resume example now
  succeeds without a socket-backed authority service.
- Validation evidence:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_example_journeys.py -q`
    passed outside the sandbox (`4 passed in 13.91s`).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py -q`
    passed outside the sandbox (`40 passed in 54.04s`).
  - `make test-e2e` passed outside the sandbox (`46 passed, 6 deselected`).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/e2e/test_example_journeys.py examples/execution/local/run_pipeline.py examples/execution/local/stages.py`
    passed.
  - `make validate-pr` passed outside the sandbox: Ruff passed, Pyright
    reported 0 errors, default harness passed (`1963 passed, 26 skipped,
    30 deselected`), config-extra passed (`460 passed, 3 skipped,
    2001 deselected`), and `uv build` succeeded.
  - `make test-summary` passed and wrote `build/test-summary.md` with overall
    suite evidence: package (`108 passed, 1 skipped`), unit (`1394 passed,
    7 skipped, 1 deselected`), contract (`274 passed, 2 skipped`),
    integration (`170 passed, 8 skipped, 18 deselected`), e2e (`46 passed,
    6 deselected`), and config-extra (`460 passed, 3 skipped,
    2001 deselected`), for `2452 passed, 21 skipped, 2026 deselected`
    overall.
- Blockers: none remaining. The initial sandboxed validation failed because the
  sandbox lacked config extras and blocked local socket creation; the approved
  outside-sandbox reruns verified the phase after targeted fixes.
- Budget status: implementation refinement unused; blocker resolution 1/3 used
  for manager-side targeted e2e/example fixes after validation exposed parser,
  assertion, and local-example hardening issues; PR review unused
- Implementation validation: targeted e2e, docs/example integration, default
  e2e gate, touched-file lint, final PR gate, and suite summary passed as
  recorded above
- Refinement summary: no separate refiner pass used
- Blocker-resolution summary: used one scoped manager pass to mark new e2e
  tests as config-extra optional dependency coverage, fix the summary parser
  and dry-run/Docker assertions, and harden the local execution example without
  touching runtime code
- PR preparation: artifact ready at
  `docs/roadmap/stage-22/phases/examples-e2e-workflows-pr-body.md`.
  PR title remains `Examples And Validation - Phase 3: E2E Workflows`;
  branch `codex/examples-e2e-workflows` targets `develop` with no stack
  predecessor. PR remains unopened for the manager to push/open.
- Stack maintenance: none required for this planning pass
- Remaining blockers: none known
