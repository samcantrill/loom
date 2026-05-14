# Phase 8 Execution Plan: Hardening, Docs, And Migration Notes

## Metadata

- Status: pr_open
- Branch: `codex/v0-post-hardening-docs`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-hardening-docs`
- Phase execution plan path: `docs/roadmap/stage-0-post/phases/v0-post-hardening-docs.md`
- Full plan: `docs/roadmap/stage-0-post/implementation-plan.md`
- Source phase: `Phase 8 - Hardening, Docs, And Migration Notes`
- PR: [#22](https://github.com/samcantrill/loom/pull/22). PR body prepared at
  `docs/roadmap/stage-0-post/phases/v0-post-hardening-docs-pr-body.md`.
- Stack predecessor: none. Serial human merge gate is active and this phase is
  not stacked on any predecessor branch.
- Base branch: `develop` at `ef5e4522e2d04b549b44ee0f0b7748ff765ed664`
- Target branch: `develop`
- Merge eligibility: serial human merge gate. The Phase 8 PR must target
  `develop`, be verified with `gh pr view <PR> --json
  baseRefName,headRefName,state,url`, request review from `samcantrill` when
  GitHub allows it, and mention `@samcantrill` in the PR body or an immediate
  fallback PR comment if GitHub rejects the reviewer request. Codex must not
  approve or merge.
- Successor dependency notes: no successor v0-post phase is recorded. V1
  planning or implementation must not proceed until Phase 8 is human-reviewed,
  human-merged into `develop`, `gh pr view <PR> --json
  state,baseRefName,headRefName,url,mergedAt` reports `state` as `MERGED` with
  `baseRefName` as `develop`, and the implementation plan records this phase as
  `merged`.
- Plan quality gate: passed in
  `docs/roadmap/stage-0-post/implementation-plan.md`; no blocking
  plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in commit `ac716be`
  (`plan: add phase 8 execution plan`).
- Refine pass: completed by `loom_phase_planner` in response to manager
  refinement goals. This pass only tightened phase boundaries, serial-gate
  details, suite obligations, and blocker conditions; it does not reopen
  architecture or public-protocol decisions.
- Phase implementation refinement budget: used on 2026-05-05 by the single
  allowed `loom_phase_refiner` pass. Refinement tightened migration-note
  completeness for renamed run metadata APIs and run-scoped artifact-store
  operations, corrected docs language that could imply implemented future
  CLI/sweep behavior, fixed focused e2e optional-config import ordering, and
  added targeted type hardening for the lock-store helper.
- PR review budget: unused.
- PR body draft/refine budget: fast-path draft used during PR preparation;
  refine not needed.
- Setup limitations: no remote synchronization or validation commands were run
  during planning. The branch and worktree were created from the local
  `develop` checkout supplied by the manager.
- Blockers: none after refinement.

## Implementation Refinement Evidence

- Refinement pass status: used once; do not run another automated
  implementation refinement pass without explicit manager instruction.
- Checks run during refinement:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/e2e/test_local_pipeline_run.py`
    initially failed during collection because config-extra imports occurred
    before optional dependency skips. After the fix, the same command passed
    with 5 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_local_pipeline_run.py`
    passed with 5 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/e2e/test_local_pipeline_run.py`
    passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright tests/e2e/test_local_pipeline_run.py`
    passed with 0 errors.
  - `git diff --check` passed.
- Remaining blockers: none known. PR preparation evidence below records final
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` and
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` results.

## PR Preparation Evidence

- PR preparation pass: completed on 2026-05-05.
- Branch confirmed: `codex/v0-post-hardening-docs`.
- Target branch confirmed: `develop`.
- Stack predecessor confirmed: none.
- Final scope inspection: docs, migration notes, downstream roadmap alignment,
  phase artifact, and focused e2e coverage only; no runtime feature files are
  changed in the final Phase 8 diff.
- Cleanliness check: `git diff --check develop...HEAD` passed.
- Validation gate:
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed. Ruff passed, Pyright
  reported 0 errors, the default harness passed with 406 passed and 9 skipped,
  the config-extra harness passed with 108 passed and 411 deselected, and
  `uv build` produced the sdist and wheel.
- Suite evidence:
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote
  `build/test-summary.md`.

| Suite | Status | Duration |
| --- | --- | ---: |
| package | passed | 2.99s |
| unit | passed | 2.66s |
| contract | passed | 1.03s |
| integration | passed | 1.44s |
| e2e | passed | 2.58s |
| config-extra | passed | 5.54s |

- Push: `codex/v0-post-hardening-docs` pushed to origin with head commit
  `9ff2e01` before PR creation.
- PR creation: opened
  [#22](https://github.com/samcantrill/loom/pull/22) against `develop`.
- PR target verification:
  `gh pr view 22 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup`
  reported `baseRefName` as `develop`, `headRefName` as
  `codex/v0-post-hardening-docs`, `state` as `OPEN`, `url` as
  `https://github.com/samcantrill/loom/pull/22`, `mergeCommit` as `null`, and
  CI `checks` as `IN_PROGRESS`.
- Reviewer notification: `gh pr edit 22 --add-reviewer samcantrill` could not
  complete. The verified PR author and authenticated GitHub account were both
  `samcantrill`, so the serial-gate fallback was used.
- Reviewer fallback comment:
  https://github.com/samcantrill/loom/pull/22#issuecomment-4375429754
- Remaining blockers: none known. CI was still in progress at target
  verification time.

## Objective

Close the v0-post hardening sequence with user-facing migration notes, final
documentation consistency checks, downstream roadmap alignment, and focused e2e
coverage for the corrected local Python runtime behavior.

This phase is a closeout and evidence phase. It is limited to migration notes,
documentation consistency, downstream plan alignment, and focused e2e or
high-level integration hardening for completed Phases 1 through 7 behavior. It
must not add new runtime features, reopen architecture decisions completed in
Phases 1 through 7, or move deferred work from future roadmap versions into
pre-v1 hardening.

## Full-Plan Context

Phases 1 through 7 are merged into `develop`. They established recursive
immutability, strict schema helpers and migrations, capability-oriented stores,
run-scoped artifact stores, `ArtifactAddress`, the stage-author
`StageContext`, explicit stage factory blocks, semantic fingerprint policy,
runtime/resource/event/lock foundations, planner policy decomposition,
explicit recipe catalogs, fresh composition, and runner lifecycle
decomposition with local event, lock, and blocked-outcome integration.

Phase 8 verifies that those changes are accurately documented, records the
breaking user-facing migration path, adds final focused coverage for the
local-only pre-v1 behavior, and records validation evidence during PR
preparation. It remains bounded by the v0-post plan: remote stores, non-local
executors, retries, timeouts, plugin discovery, sweeps, run catalogs, bundles,
cleanup, and retention remain deferred.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 7 PR #21 is merged into
  `develop` and recorded.
- Why this base branch is correct: serial human merge gate mode starts each
  phase from updated `develop`, and the Phase 7 merge notes say Phase 8 must
  continue from updated `develop`.
- Retarget/rebase plan after predecessor merge: not applicable because there
  is no unmerged predecessor and the PR target is already `develop`.
- Review notification plan: after opening or discovering the PR, request
  `samcantrill` as reviewer with `gh pr edit <PR> --add-reviewer samcantrill`
  when GitHub permits it. If GitHub rejects that request because the
  authenticated account or PR author is `samcantrill`, add an immediate PR
  comment mentioning `@samcantrill` and record the fallback in the PR body or
  phase notes.
- Successor start rule: no successor phase or v1 implementation starts while
  this PR is `pr_open` or `approved`; continue only after GitHub reports the PR
  as `MERGED` into `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.

## Source Phase Summary

- Goal: close the pre-v1 hardening work with migration notes, end-to-end
  coverage, roadmap alignment, and final documentation consistency.
- Required scope:
  - Verify `docs/loom.md`, `docs/structure.md`, and affected feature docs
    reflect the phase-local contract changes from Phases 1 through 7.
  - Add migration notes for renamed or removed v0 APIs and expected
    user-facing changes.
  - Update downstream implementation plans so v1 starts after this hardening
    sequence and does not repeat superseded assumptions.
  - Add focused e2e coverage for local run success, failure with blocked
    outcomes, resume/reuse, explicit catalog composition, stage factory
    construction, and local event/lock behavior.
  - Run final validation gates during PR preparation and record suite-level
    evidence.
- Acceptance criteria:
  - Docs describe only supported pre-v1 behavior and explicitly defer remote
    stores, non-local executors, retries, timeouts, plugin discovery, sweeps,
    catalogs, bundles, cleanup, and retention behavior.
  - Migration notes identify breaking API changes and replacement APIs.
  - `make validate-pr` passes.
  - `make test-summary` records suite-level evidence.
  - The implementation plan status can move to complete only after all earlier
    phases are merged.

## Current Source And Harness Findings

- The repository already has targeted unit, contract, integration, e2e, and
  package/import tests for the v0-post surfaces introduced by earlier phases.
  Phase 8 should add only focused closeout coverage that demonstrates the
  surfaces work together through public APIs.
- Existing e2e entry point: `tests/e2e/test_local_pipeline_run.py`.
- Relevant integration coverage already lives under `tests/integration/config/`
  and `tests/integration/pipeline/`, including config composition, local
  execution, resume, failure, stores, plan persistence, and docs examples.
- Package/import guardrails already live under `tests/package/`, including API
  and import-boundary coverage. Phase 8 should preserve and tighten these only
  where docs or migration notes expose final pre-v1 public imports.
- The implementation plan's overall test plan already requires package, unit,
  contract, integration, e2e, default validation, and config-extra evidence in
  `make test-summary`.

## In-Scope Work

- Add migration notes in a durable docs location, linked from the README or
  main docs, that map removed or renamed pre-v1 APIs to replacements:
  - generic local path-shaped store/context access to capability-oriented store
    APIs and explicit local-only path helpers;
  - run metadata naming ambiguity to run-document and user-metadata APIs;
  - artifact-store operations with `run_id` parameters to run-scoped artifact
    stores;
  - cross-run artifact references to `ArtifactAddress(run_id, artifact_id)`;
  - no-argument stage construction and stage runtime config mixing to explicit
    `factory: {_target_: ..., init: {...}}` plus runtime `stage_config`;
  - stage context direct filesystem assumptions to `StageContext` author
    helpers such as artifact save/register/load and local-only output helpers;
  - process-global recipe registration as convenience to explicit
    `RecipeCatalog` and fresh-catalog composition for reproducible workflows.
- Perform a documentation consistency pass over `docs/loom.md`,
  `docs/structure.md`, and affected `docs/features/` pages. Update only stale
  statements or missing closeout links caused by completed v0-post contract
  changes.
- Update downstream implementation plans and roadmap docs only where they still
  assume superseded v0 contracts or need an explicit "starts after v0-post
  hardening" note.
- Add focused e2e or high-level integration coverage for:
  - successful local run through public Python APIs;
  - failed local run that persists failed and blocked outcomes;
  - same-run resume/reuse after the v0-post fingerprint and store changes;
  - explicit catalog composition that ignores process-global recipe history;
  - stage factory construction with separate factory init and runtime
    `stage_config`;
  - local lifecycle events and run lock behavior visible through supported
    store APIs.
- Preserve permanent import-boundary and no-extra/config-extra guardrails.
- Keep runtime edits limited to small hardening fixes required by focused tests
  or documentation corrections. Do not introduce future runtime features under
  the closeout label.
- During PR preparation, run `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` and
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary`; record suite-level evidence
  in the PR body and phase completion notes.

## Out-of-Scope Work

- No architecture decision changes for store capabilities, `StageContext`,
  `ArtifactAddress`, schema migration helpers, stage factory syntax, semantic
  fingerprint policy, event records, run locking, planner explanations, recipe
  catalogs, or runner lifecycle boundaries.
- No functional CLI commands, parser behavior, terminal output design, or exit
  code mapping.
- No remote artifact stores, remote run stores, run catalogs, bundles,
  cross-run cache reuse, sweeps, dashboards, or database-backed orchestration.
- No subprocess, SLURM, container, distributed, retry, timeout, cleanup,
  retention, or stale-lock recovery behavior.
- No plugin discovery, entry-point loading, import allow lists, config
  sandboxing, Hydra defaults, include graphs, or v1 config composition work.
- No domain stages, domain codecs, domain recipes, schema inference,
  project-specific datasets, model/report helpers, or non-generic examples.
- No broad docs rewrite unrelated to the completed v0-post contract changes.
- No implementation-plan metadata update to `merged`; that belongs after the
  human merge is verified on `develop`.

## Assumptions

- Breaking pre-v1 changes from Phases 1 through 7 are accepted and should be
  documented directly rather than hidden behind compatibility shims.
- Documentation that defines a package boundary or public contract should
  already have moved with the phase that changed it. Phase 8 may correct drift
  but should not carry major missing contract design for earlier phases.
- Focused e2e coverage should use public APIs and supported store inspection
  paths. Tests should avoid depending on private helper objects unless the
  existing suite already treats them as internal unit boundaries.
- Some docs examples may remain illustrative when they necessarily reference a
  downstream project stage. Generic examples that use in-repo helpers or public
  APIs should be mirrored by tests where feasible.
- `make test-summary` is the source of suite-level PR evidence.

## Suite-Level Test Obligations

| Suite | Required Phase 8 obligation |
| --- | --- |
| Package/import | Preserve cheap `import loom`, no-extra import behavior, public API exports, and final import-boundary guardrails. Add or adjust package tests only if migration notes or docs expose final public import paths. |
| Unit | Add unit tests only for narrow docs-closeout or migration-note behaviors that cannot be proven through higher-level tests. Existing unit coverage for events, locks, stage factory, recipe catalogs, planning, stores, and status must continue to pass. |
| Contract | Preserve structural stage, codec, recipe, store, and executor contract tests. Add contract coverage only if final migration notes expose a replacement contract not already tested. |
| Integration | Use focused integration coverage where cross-module behavior is clearer than e2e: explicit catalog composition unaffected by global recipes, stage factory plus `stage_config`, same-run resume/reuse, and runner-visible event/lock behavior. |
| E2E | Add or refresh a small number of public-API e2e tests that exercise local success, failure with durable blocked outcomes, resume/reuse, explicit catalog composition, stage factory construction, and local events/locks without relying on private internals. |
| Opt-in/config-extra | Preserve the opt-in config-extra suite and its `make test-summary` evidence row. Any tests requiring config composition extras must run under the existing opt-in/config-extra target rather than weakening no-extra package/import behavior. |
| Validation gates | PR preparation must run `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` and `UV_CACHE_DIR=/tmp/uv-cache make test-summary`; failures must be fixed or recorded as blockers before PR open/preparation completes. CI failures after PR creation are blockers unless clearly unrelated and recorded with evidence. |

## Design Impact

- Maintainability: consolidates the closeout evidence for the v0-post sequence
  without hiding new subsystem design inside a docs phase. Migration notes give
  users one reviewable map of breaking pre-v1 changes.
- Extensibility: confirms future v1 and later roadmap work starts from the
  corrected store, artifact, stage, planning, recipe, event, lock, and runner
  contracts instead of carrying local-v0 assumptions forward.
- Domain neutrality: examples and tests must stay generic. Migration notes may
  describe project-owned stages, recipes, and stores, but runtime code and
  executable examples must not introduce domain concepts.
- Source-tree boundaries: docs should reflect existing package ownership.
  Tests should use public APIs or established test boundaries, not new
  cross-package shortcuts.

## Future Compatibility

- V1 config composition can proceed after this phase with explicit awareness of
  trusted config, fresh recipe catalogs, stage factory blocks, and corrected
  fingerprint boundaries.
- V2 CLI work can rely on migration notes and documentation that distinguish
  supported Python APIs from deferred CLI commands.
- Later remote-store, executor, run-catalog, bundle, sweep, plugin, retry,
  timeout, cleanup, and retention phases can build on documented deferrals
  rather than revisiting pre-v1 local-runtime debt.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reopen architecture decisions while writing migration notes | The v0-post implementation plan already passed review and Phases 1 through 7 are merged. Phase 8 is a closeout pass, not a second architecture gate. |
| Add broad new e2e scenarios for every subsystem | Existing unit, contract, and integration suites own detailed behavior. Phase 8 should prove corrected surfaces compose through public APIs without making the e2e suite slow or brittle. |
| Convert docs to CLI-first guidance | Functional CLI commands are post-v0. Pre-v1 docs should be Python-API-first and explicit about CLI deferral. |
| Add compatibility shims for removed pre-v1 APIs | Breaking changes are intentionally accepted before v1 where they correct long-term contracts. Migration notes are the support path unless a missing shim is already required by an accepted public contract. |
| Start v1 implementation cleanup in this phase | V1 remains downstream work. Phase 8 may update downstream plans for accuracy but must not implement v1 composition features. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Migration support is documentation-first rather than compatibility-shim based | Pre-v1 breaking changes are allowed and the package should not preserve misleading local-v0 contracts. | A downstream user needs a short-lived compatibility bridge before v1 public API stabilization. |
| Some project-code snippets may remain illustrative | `loom` must stay domain-neutral and cannot ship downstream project stages. | A future examples package or tutorial repository is created. |
| E2E coverage remains focused rather than exhaustive | Detailed behavior is already covered by unit, contract, and integration suites; broad e2e duplication would slow review. | A public workflow fails despite lower-level coverage, or PR evidence stops showing meaningful cross-surface validation. |
| Deferred roadmap docs still describe future features separately from implemented behavior | Remote stores, executors, plugins, sweeps, catalogs, bundles, cleanup, and reliability policies are intentionally future work. | A later roadmap phase starts and promotes one of those designs into implemented contracts. |

## Reviewability

- Expected PR size and shape: documentation and migration-note closeout plus a
  focused set of high-level tests. Source changes should be limited to small
  hardening fixes required by those tests or docs corrections.
- Files and areas to inspect: migration notes, README/main docs links,
  `docs/loom.md`, `docs/structure.md`, affected feature docs, downstream
  implementation plans, focused e2e/integration tests, and package/import
  guardrails.
- Scope-control checks: no new backend, CLI command, remote-store behavior,
  plugin discovery, sweep/catalog/bundle implementation, retry/timeout/cleanup
  policy, or domain-specific runtime code.
- Evidence to expect in the PR body: `make validate-pr` result and
  `make test-summary` suite rows for package, unit, contract, integration,
  e2e, and config-extra/default validation surfaces.

## Stop Conditions

- Stop and report a blocker if migration notes require an unplanned public API
  compatibility decision.
- Stop if focused e2e coverage exposes a cross-phase behavioral gap that
  cannot be fixed without implementing a deferred feature or reopening an
  architecture decision.
- Stop if validation cannot run in the PR preparation environment, or if
  failing validation cannot be resolved within Phase 8 scope.
- Stop if CI is clearly failing and the failure cannot be resolved within Phase
  8 scope or justified as unrelated with evidence.
- Stop if GitHub PR creation, PR inspection, or target verification cannot
  satisfy the serial human merge gate requirements. A PR targeting anything
  other than `develop` is a blocker.
- Stop if GitHub reviewer notification cannot request `samcantrill` and the
  required `@samcantrill` fallback comment cannot be posted and recorded.
- Stop if the PR is closed without merge, GitHub access needed to poll the
  serial gate is unavailable, or GitHub does not report the human-owned PR as
  `MERGED` into `develop` before successor work would start.
