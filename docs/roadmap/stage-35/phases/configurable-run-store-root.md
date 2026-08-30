# Phase 1 Execution Plan: Configurable Run-Store Root

## Metadata

- Status: ready to merge
- Roadmap stage and phase: Stage 35, Phase 1
- Manifest: `docs/roadmap/stage-35/implementation-plan.md`
- Branch: `agent/stage-35-p1-configurable-run-store-root`
- Worktree root and path: `/nas/home/can134/work/loom-worktrees`;
  `/nas/home/can134/work/loom-worktrees/stage-35-p1-configurable-run-store-root`
- Base revision: current `origin/develop` after the planning packet merges
- PR target: develop
- PR title: `Stage 35 phase 1: configure CLI run store roots`
- Dependencies: approved Stage 35 planning packet and existing authority-backed
  run-store factories
- Workflow path: expanded; optional public runtime shape plus resume/plugin
  trust ordering
- Blockers: none

## Objective And Context

- Vertical outcome: a composed config can select an absolute run collection,
  and validate, fresh run, resume, plan, Slurm, and offline CLI paths all use it
  through Loom's existing authority/store implementation.
- Earlier dependency: current `RunOptions` merge and authority-backed factories
  remain authoritative.
- Later work explicitly out of scope: GPU admission, new store backends,
  migrations, remote storage, queue deployment roots, and run URI redesign.

## Current Source And Harness

- Relevant files and symbols: `RunOptions`, runtime profile normalization and
  merge, `merge_config_run_options`, CLI run/plan/validate flows,
  `_create_default_run_store`, authority/offline factories, and local path
  parity consumers.
- Existing tests and seams: runtime option/profile tests, CLI factory spies,
  resume plugin activation ordering, Slurm dry-run/live tests, local store
  integration, and package/public API assertions.
- Import, dependency, or harness constraints: store construction stays in CLI
  and existing factories; runtime models must not import CLI; no filesystem
  mutation during option parsing.

## Scope

In scope:

- Add immutable `RunStoreOptions(root: str | None)` with explicit absolute
  canonical path validation and intentional runtime/pipeline exports.
- Add optional `run_store` to `RunOptions`, safe/plain projections, field
  validation, runtime sources, profile normalization, and nested merge.
- Add the narrow pre-plugin bootstrap projection needed to determine the same
  selected root/profile that the final plugin-aware merge will validate.
- Reorder fresh/resume CLI setup only as needed to compose before store
  construction while retaining persisted plugin activation validation before
  plugin loading.
- Pass the selected root through every normal/offline/Slurm run-store factory
  and plan store that opens or persists a configured run.
- Document config, default, profile, Python-injected-store, and path-parity
  behavior.

Out of scope:

- Store protocol/backend selection, queue daemon deployment config, automatic
  directory creation during validation, URI changes, remote stores, migration,
  and executor/GPU changes.

Assumptions:

- Weave has resolved environment expressions and includes before Loom receives
  the config.
- An explicit path can be canonicalized/validated without requiring it to
  exist; actual filesystem errors remain store-boundary failures.
- Direct Python runners that receive an explicit store keep that store as their
  authority; the config field controls CLI-created stores.

## Fixed Contracts And Private Discretion

- Observable behavior: omitted root uses `runs`; explicit root round-trips and
  is honored by fresh/run/resume/plan/Slurm/offline CLI paths; invalid paths fail
  with path-aware runtime errors.
- Public or durable shapes: `RunStoreOptions` and optional
  `RunOptions.run_store`; an unset field does not rewrite all existing plain
  options documents.
- Trust and failure boundaries: resume opens the configured store before
  persisted plugin activation validation and imports plugins only afterward;
  final merge must agree with bootstrap.
- Cross-phase contracts: Phase 2 may rely on the merged Loom commit but must not
  alter storage behavior.
- Reproducibility and compatibility: machine path is runtime evidence, not a
  pipeline/scientific fingerprint; omitted config remains compatible.
- Private choices the executor may simplify: bootstrap helper names, exact
  local factoring, and whether factory kwargs use a tiny typed record or plain
  private mapping.

## Proportionality

- Existing seam reused: `RunOptions`, profile merge, `LocalRunStore(root)`, and
  authority/offline factories.
- Material additions and current justification: one optional value plus one
  bootstrap projection are required because the store must be located before
  resume plugin activation can be trusted.
- Optional hardening and future capability deferred: existence/permission
  probes, backend registries, URI-root equivalence, migrations, and queue config
  unification.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Explicit root has one stable absolute spelling | `RunStoreOptions` parser | Composed config/profile | Processes open different collections or mounts | model invalid/round-trip tests |
| Profile/bootstrap/full merge choose one root | runtime profile/bootstrap merge | CLI-selected profile before plugins | Resume trusts the wrong prior run | precedence and equality-guard tests |
| Every CLI-created store uses the selected root | CLI factory wiring | fresh/resume/plan/Slurm/offline entrypoints | state silently lands under `./runs` | factory-spy plus persisted-root integration |
| Python-injected store is not silently replaced | Python runner boundary | caller passes options and store | authority inversion | docs and existing runner tests |

## Implementation Slices

1. Add the typed run-store option, public exports, plain/safe projections, and
   focused model tests.
2. Extend runtime profile/source normalization and merge with base/profile/
   explicit precedence tests.
3. Add the narrow bootstrap projection and wire normal/resume/offline/Slurm
   run flows with ordering and root-consistency tests.
4. Wire plan/read-only stores, validate behavior, documentation, and one
   persisted configured-root integration journey.
5. Run targeted and full gates and update only this phase's workflow state.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional cheap exports and import direction | runtime/pipeline API and import-boundary assertions |
| Unit | required | Model, path validation, profile precedence, CLI factory args/order | focused options/profiles/run/plan/validate cases |
| Contract | required via final gate | Existing RunOptions/runtime envelopes remain compatible when field omitted | existing contract suite plus explicit configured projection if appropriate |
| Integration | required | Profile-selected root and persisted run/artifact layout | one real local store/factory journey |
| E2E / opt-in | required via final gate / live deferred | CLI config uses selected root; no external backend | hermetic CLI case; no live infrastructure |

Targeted commands:

    uv run pytest tests/unit/loom/pipeline/test_runtime_options.py tests/unit/loom/pipeline/test_runtime_profiles.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_plan.py tests/unit/loom/cli/test_validate.py tests/integration/pipeline/test_runtime_profiles_integration.py
    uv run ruff check src/loom/pipeline/runtime src/loom/cli tests/unit/loom/pipeline tests/unit/loom/cli

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: changing every default serialized document; duplicating profile
  semantics; importing plugins before resume activation validation; missing a
  Slurm/offline store factory; treating a configured root as a backend.
- Review focus: omission compatibility, bootstrap/full equality, authority
  factory reuse, all call sites, path evidence/fingerprint separation, and
  absence of unrelated store refactoring.
- Stop if: the root requires a persisted schema migration, new backend type,
  queue deployment redesign, or plugin import before activation validation.
- Accepted debt and revisit trigger: one narrow bootstrap projection duplicates
  only selected-profile/run-store extraction; revisit if another pre-plugin
  runtime field becomes necessary.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above.
- Decisions not to revisit: optional `None` default, canonical absolute explicit
  path, existing authority factories, CLI-only construction semantics, final
  bootstrap equality, and no backend/migration work.
- Conditions requiring manager action: an unavoidable trust-order reversal,
  durable migration, public shape conflict, or inability to cover a supported
  CLI store-construction path.

## Workflow State

- Manager preparation: completed; implementation started from approved
  `8da9536d351dba46c6737465839a40802f547f5b` and was cleanly rebased before PR
  onto current `develop` at `a3a4507` with no overlapping path.
- Expanded planning: completed; the bounded review found no run-store blocker.
- Implementation: completed in `e2b0f002e9f14ffcd43adacb0666ca43289c7f32`;
  the bounded resume trust-order correction is
  `23dc239efa90f3277585e63ce3dba730d5bda627`; the bounded sparse-merge and
  lexical-path correction is
  `842a8d05f6e4927287491bc8cb4d1fc9617d7c96`.
- Refiner: not needed unless a qualified blocker appears.
- Pre-submit gate: passed on corrected source/test revision
  `842a8d05f6e4927287491bc8cb4d1fc9617d7c96`.
- Independent review: completed for resume/bootstrap and configured-root trust
  boundaries. Its sparse nested-merge and filesystem-probing blockers, plus the
  localized runtime-metadata documentation correction, are resolved and
  manager-verified.
- Blocker corrections: 2/3 correction passes consumed. Slurm resume validates
  persisted activation before plugin imports; empty nested overlays preserve a
  lower root, explicit null clears it, and path normalization is lexical.
- PR and merge: #258 is ready for its corrected branch update and merge.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `RunStoreOptions` and optional `RunOptions.run_store`, sparse runtime profile/config bootstrap projection, CLI run/plan authority/offline/Slurm root wiring, public exports, and feature documentation. Changed `src/loom/pipeline/runtime/{options,profiles,config,__init__}.py`, `src/loom/pipeline/__init__.py`, `src/loom/cli/{run,plan}.py`, and `docs/features/{execution,cli}.md`. Manager correction `23dc239e` made the existing resume-store/activation check common to normal, Slurm dry-run, and Slurm live entrypoints. Manager correction `842a8d0` preserved authored nested-field sparsity and replaced filesystem-resolving normalization with lexical normalization. |
| Tests added or updated | Added option/path and profile-precedence tests, sparse empty-overlay and explicit-null tests for bootstrap and full merging, a symlink-containing lexical-path regression, resume/bootstrap and plan factory-spy tests, public export checks, a real profile-selected fresh/resume CLI journey under the configured collection, and both Slurm resume import-order failure cases. |
| Validated revision/tree state and evidence | Corrected source/test revision `842a8d05f6e4927287491bc8cb4d1fc9617d7c96`; fresh `make validate-pr` passed (Ruff; Pyright with zero errors; default: 2,631 passed/135 deselected; config-extra: 156 passed/3 skipped/2,634 deselected; sdist and wheel built). The earlier executor `make test-summary` receipt at the equivalent pre-rebase implementation had one unrelated queue timestamp-race failure; its isolated rerun passed without a source change. |
| Validation-relevant changes after evidence | none; this completion metadata only |
| PR, review, and merge | PR #258; independent review completed, all blockers corrected and manager-verified; merge pending. |
| Residual risk and cleanup | No Phase 1 blocker. Direct per-factory Slurm root assertions remain optional hardening because existing factory-spy and integration coverage exercise the shared root path. The earlier `make test-summary` anomaly remains classified as an unrelated `scheduler_observed_at` timestamp race because its isolated rerun passed and the fresh required pre-submit gate passed. Worktree and branch remain through merge verification. |
