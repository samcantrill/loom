# Phase 6 Execution Plan: End-To-End Hardening And Documentation

## Metadata

- Status: implemented; validation passed; PR body prepared
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 6: End-To-End Hardening and Documentation`
- Branch: `codex/slurm-dry-run-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-dry-run-hardening`
- Phase execution plan path: `docs/phases/slurm-dry-run-hardening.md`
- PR body path: `docs/phases/slurm-dry-run-hardening-pr-body.md`
- Full plan: `docs/implementation-plans/implementation-plan-v6.md`
- Source phase: Phase 6 - End-To-End Hardening And Documentation
- PR: pending
- PR state: pending
- Stack predecessor: none; Phases 1-5 are merged into `develop`
- Base branch: `develop` at `9f4c4b2`
- Target branch: `develop`
- Merge eligibility: root phase; not merge-eligible until PR is open, automated
  review passes, GitHub CI passes, PR body evidence is accurate, and the PR
  targets `develop`
- Workflow path: expanded path because the phase spans e2e behavior, persisted
  secret-boundary contracts, feature documentation, and v7 handoff notes
- Successor dependency notes: this is the final v6 phase. No successor phase
  should branch from this worktree unless a later roadmap plan explicitly adds
  one.
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement
  pass, and confirmation review
- Plan quality gate loop budget: initial review used, refinement used,
  confirmation review used
- Draft pass: completed locally by the managing agent from the Phase 6 source
  scope and current Phase 1-5 artifacts
- Refine pass: completed locally in the same artifact after source/test/doc
  scans identified the concrete hardening gaps below
- Setup limitations: branch/worktree were created from local `develop` after
  Phase 5 merge metadata was pushed. No product-code validation or broad checks
  were run during this planning pass.
- Blockers: none known after local validation

## Objective

Close v6 by proving the public SLURM dry-run CLI contract end to end, hardening
the secret-boundary regression coverage across persisted artifacts, and updating
the feature docs so they describe the implemented v6 dry-run behavior and the
remaining v7 live-submission handoff without implying scheduler calls exist in
v6.

## Full-Plan Context

Phases 1-2 added generic prepared-run and stage-job continuation. Phases 3-4
added SLURM modes, option/resource mapping, script rendering, manifests, and
Python dry-run APIs. Phase 5 exposed the public `loom run --executor
slurm-single-job --dry-run` and `loom run --executor slurm-afterok --dry-run`
surfaces plus diagnostics/preflight checks.

Phase 6 must not add live `sbatch`, scheduler IDs, scheduler state,
status/cancel behavior, controller mode, containers, job arrays, or generic
wall-time resources. It should make the already-implemented dry-run contract
hard to regress and make the docs stop recommending stale resolved-config or
`loom stage run` command shapes for v6 generated scripts.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; PRs #82-#86 are merged and recorded
  in the v6 implementation plan
- Why this base branch is correct: all earlier v6 phases are merged into
  `develop`, and Phase 5 metadata is pushed on `develop`
- Retarget/rebase plan after predecessor merge: none required unless `develop`
  moves before PR preparation, in which case rebase this branch onto updated
  `develop` and rerun focused validation
- Branch cleanup constraints: branch can be deleted after merge because no v6
  successor branch should depend on it

## Source Phase Summary

- Goal: close v6 with cluster-free end-to-end evidence, documentation updates,
  and compatibility checks across generic continuation and SLURM dry-run
  surfaces.
- Required scope: add final e2e artifact inspection for both modes; add
  regression coverage for the secret-boundary matrix; add fan-in/fan-out/diamond
  examples and docs; update feature docs where v6 supersedes resolved-config or
  v5 worker-command examples; record v7 handoff notes and deferred work.
- Required exclusions: no live cluster tests, `sbatch`, scheduler status/cancel,
  containers, job arrays, controller mode, or generic wall-time resources.
- Acceptance criteria: final validation covers both SLURM modes, continuation
  commands, secret-safe artifacts, repeated dry-runs, dependency shapes, and
  docs/v7 handoff; any uncovered secret-boundary surface is recorded as accepted
  risk with a revisit trigger.

## Current Source And Harness Findings

- `tests/e2e/test_cli_slurm_dry_run.py` proves both public CLI modes create
  manifest, plan, script, root `plan.json`, and `prepared_run.json` files
  without a scheduler, but it does not inspect manifest contents, generated
  commands, repeated dry-run separation, diamond dependencies, wrapper log
  paths, or secret-boundary strings across the persisted artifact set.
- `tests/integration/config/test_cli_run.py` covers CLI single-job and afterok
  routing, profile-resolved SLURM dry-run routing, stage-level SLURM option
  application, and v7-deferred live-mode errors. It contains only a narrow
  `SECRET` assertion for `prepared_run.json`.
- `tests/integration/pipeline/test_slurm_dry_run_planning.py` covers Python API
  artifact writes, manifest round-trip, afterok diamond dependencies, repeated
  planning IDs, and omission of the v5 `loom stage run` command in afterok
  scripts. It uses synthetic store metadata and does not exercise public CLI
  config resolver outputs or environment values.
- Unit/contract tests already cover SLURM manifest schema, options, resource
  mapping, script rendering, generated paths, CLI output schema, continuation
  command envelopes, runtime metadata summaries, and preflight stable IDs.
  Phase 6 should extend them only where e2e/integration hardening exposes a
  concrete gap.
- `docs/features/slurm.md` is still a broad design document with current
  examples that mention live `sbatch --parsable`, submitted/cancel/status
  behavior, `SUBMITTED` state, `loom stage run`, and resolved-config command
  sources. V6 docs need a clear implemented dry-run contract and must label
  live scheduler sections as v7/later.
- `docs/features/cli.md` mentions SLURM examples and `loom stage run` in places
  that predate the v6 `prepared-run continue` and `stage-job run` command
  shapes. The CLI docs should distinguish generic plan dry-runs from SLURM
  dry-run artifact generation.
- `docs/features/execution.md`, `docs/features/pipeline.md`, and
  `docs/features/preflight.md` contain future SLURM/resolved-config wording that
  should remain future-scoped and should not contradict v6 dry-run behavior.

## In-Scope Work

- Extend public CLI e2e coverage so one representative test inspects both
  SLURM modes' generated manifests, plans, scripts, wrapper log paths, command
  argv, and root run records.
- Add a secret-boundary regression that drives a public config with `oc.env`
  resolver expressions and secret-looking environment values through SLURM
  dry-run planning, then scans the assigned persisted surfaces:
  `prepared_run.json`, root `plan.json`, stage metadata/fingerprint records
  when present, runtime/config records, SLURM manifest, SLURM dry-run plan,
  generated scripts, wrapper log paths, and typed SLURM options.
- Add or extend coverage for repeated CLI dry-runs and a diamond afterok graph
  so the final behavior covers fan-in, fan-out, and dependency-shape examples
  from the implementation plan.
- Update `docs/features/slurm.md` with an implemented-v6 section that documents
  dry-run modes, artifact layout, manifest fields, logical job keys,
  continuation command shapes, missing-`sbatch` warning behavior, secret
  boundary, repeated planning IDs, and v7-deferred live operations.
- Update `docs/features/cli.md`, `docs/features/execution.md`,
  `docs/features/pipeline.md`, and `docs/features/preflight.md` only where
  needed to remove current-behavior contradictions around resolved-config
  replay, `loom stage run` as the submitted afterok worker, and live SLURM
  operations in v6.
- Record Phase 6 completion metadata in the v6 implementation plan after
  validation evidence exists and prepare a concise PR body with suite-level
  evidence.

## Out-of-Scope Work

- Live `sbatch`, `squeue`, `sacct`, `scancel`, job ID parsing, status/cancel
  CLI commands, partial submission recovery, scheduler state, or submitted run
  statuses.
- Real cluster or opt-in scheduler tests.
- Container wrapping, MPI, job arrays, controller mode, retries, timeout
  enforcement, cleanup/retention policy, remote stores, bundles, sweeps, plugin
  discovery, or run catalogs.
- Generic wall-time resources or broad resource-model redesign.
- Changing the v5 `loom stage run` handoff-only worker contract.
- Persisting unredacted resolved config, resolver outputs, environment variable
  values, raw adapter payloads, or full environment snapshots by default.

## Assumptions

- Most Phase 6 changes should be tests, docs, phase metadata, and PR evidence.
  Product-code edits are acceptable only for a concrete hardening failure found
  by the new tests.
- Authored config and SLURM prelude lines remain trusted project code; the
  secret-boundary regression should check Loom-generated payloads and should not
  treat user-authored prelude text as a sanitization boundary.
- Existing unit and contract suites already provide most focused schema and
  helper coverage. Phase 6 should prefer representative e2e/integration
  coverage over duplicating the full unit matrix.
- If a secret-boundary surface has no file in a dry-run scenario, the test may
  assert its absence and record that as the surface evidence.

## Scope Contract

Phase 6 does not change the public v6 API shape unless a regression is found.
The public behavior to prove is:

```text
loom run CONFIG --executor slurm-single-job --dry-run
loom run CONFIG --executor slurm-afterok --dry-run
```

Both commands create a local run directory, persist root `plan.json` and
`prepared_run.json`, write a distinct `slurm/submissions/<planning_id>/...`
artifact tree for each dry-run attempt, report missing `sbatch` as a warning
when applicable, and emit JSON schema `loom.cli.slurm_dry_run.v1`.

Generated single-job scripts must invoke:

```text
loom prepared-run continue --run-uri RUN_URI --executor local
```

Generated afterok scripts must invoke:

```text
loom stage-job run --run-uri RUN_URI --stage STAGE --executor local
```

The generated manifest and scripts use logical job keys in v6. Scheduler job
IDs, raw job IDs, submitted state, scheduler state, and live submission records
remain absent or null.

## Design Impact

- Maintainability: converts v6's cross-surface dry-run contract into focused
  regression evidence instead of relying on scattered lower-level tests.
- Extensibility: leaves v7 with stable dry-run artifacts, logical job keys, and
  continuation command shapes for live submission to build on.
- Domain neutrality: keeps SLURM-specific docs and tests under executor-facing
  surfaces while preserving generic execution and CLI boundaries.
- Source-tree boundaries: CLI tests should exercise public commands; lower
  layers must continue to avoid importing `loom.cli`; SLURM-specific logic
  remains under `loom.pipeline.executors.slurm`.

## Future Compatibility

- V7 can add `sbatch`, scheduler job IDs, partial submission records, status,
  cancellation, and recovery on top of the tested dry-run manifest and logical
  dependency model.
- Later containers can reuse `prepared-run continue` and `stage-job run`
  commands inside their launchers.
- Later real-cluster acceptance can be opt-in without weakening the default
  cluster-free suite.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Treat Phase 5 e2e coverage as sufficient | It proves file creation, not the final manifest/script/log/dependency/secret contract. |
| Add live `sbatch` smoke tests | V6 explicitly remains cluster-free and dry-run-only. |
| Move generated-command logic into CLI docs/tests only | Generated commands are executor artifacts; CLI coverage should inspect the public result, not own script generation. |
| Keep stale live-submission examples as current behavior | They contradict the v6 dry-run-only scope and risk misleading v7 handoff work. |
| Persist resolved config values to make replay examples simpler | The implementation plan rejects resolved-config replay because resolver outputs and environment values can contain secrets. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No real cluster acceptance evidence in v6 | Default validation must be deterministic, local, and scheduler-free. | V7 live submission or an opt-in cluster acceptance suite starts. |
| Secret-boundary coverage remains representative rather than exhaustive across every resolver and config shape | Exhaustive resolver/redaction matrices already live in config suites; Phase 6 needs the public SLURM dry-run path. | A resolver or adapter path is added that can bypass artifact-safe config records. |
| Docs may retain future live SLURM design sections | They are useful v7 planning material when clearly labeled as deferred. | Readers or tests continue confusing future live behavior with implemented v6 behavior. |

## Reviewability

- Expected PR size and shape: mostly e2e/integration tests and docs, with
  product-code fixes only if the new hardening tests expose a real bug.
- Files and areas to inspect: `tests/e2e/test_cli_slurm_dry_run.py`,
  `tests/integration/config/test_cli_run.py`,
  `tests/integration/pipeline/test_slurm_dry_run_planning.py`,
  `docs/features/slurm.md`, `docs/features/cli.md`,
  `docs/features/execution.md`, `docs/features/pipeline.md`,
  `docs/features/preflight.md`,
  `docs/implementation-plans/implementation-plan-v6.md`, and the PR body.
- Scope-control checks: no live scheduler calls, no scheduler IDs, no
  submitted statuses, no status/cancel commands, no generic wall-time redesign,
  no source-tree boundary drift, and no persistence of resolver outputs or
  environment values by default.

## Implementation Steps

1. Add/extend e2e and integration helpers for a diamond SLURM dry-run config
   with `oc.env` expressions and secret-looking values.
2. Add artifact assertions for both public CLI modes: manifest fields, script
   commands, wrapper log paths, dry-run plan, root plan/prepared-run records,
   repeated planning IDs, and logical afterok dependencies.
3. Run the targeted SLURM and CLI suites; fix only concrete failures within
   Phase 6 scope.
4. Update feature docs to describe implemented v6 dry-run behavior and clearly
   label live submission/status/cancel as v7/later.
5. Run `make validate-pr` and `make test-summary`, then update Phase 6
   metadata and prepare the PR body with suite-level evidence.

## Test Plan

### Package Suite

- Status: required final evidence; new tests conditional
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_public_api.py`, and
  `tests/package/test_import_boundaries.py` through `make validate-pr`
- Required assertions or deferral reason: package imports and boundaries remain
  stable without optional SLURM/runtime dependencies. Add package tests only if
  docs or fixes change exports.

### Unit Suite

- Status: required final evidence; new tests conditional
- Expected paths: existing SLURM, CLI, diagnostics, runtime, and continuation
  unit suites through `make validate-pr`; focused development command may run
  `tests/unit/loom/pipeline/executors/slurm`, `tests/unit/loom/cli`, and
  `tests/unit/loom/diagnostics`
- Required assertions or deferral reason: existing unit coverage must continue
  to prove stable options, scripts, manifest helpers, diagnostics IDs, and CLI
  output. Add new unit tests only for a product-code fix.

### Contract Suite

- Status: required final evidence; new tests conditional
- Expected paths: `tests/contracts/test_slurm_manifest_contract.py`,
  `tests/contracts/test_cli_run_slurm_contract.py`,
  `tests/contracts/test_continuation_commands_contract.py`,
  `tests/contracts/test_diagnostics_preflight_contract.py`, and full contract
  suite through `make validate-pr`
- Required assertions or deferral reason: manifest/script command schema and
  CLI envelopes remain stable. Add contract tests only if Phase 6 changes a
  public schema or error shape.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/config/test_cli_run.py`,
  `tests/integration/pipeline/test_slurm_dry_run_planning.py`,
  `tests/integration/pipeline/test_prepared_run_continuation.py`, and
  `tests/integration/pipeline/test_stage_job_continuation.py`
- Required assertions or deferral reason: repeated dry-run attempts, secret
  boundary surfaces, generated artifacts, continuation commands, and Python API
  planning behavior must remain covered without a scheduler.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_slurm_dry_run.py` and full e2e suite
  through `make test-summary`
- Required assertions or deferral reason: both public SLURM dry-run CLI modes
  must be exercised with generated artifact inspection, diamond dependency
  shape, missing-`sbatch` warning behavior, and no live scheduler calls.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: real SLURM/cluster coverage is
  explicitly deferred to v7 or later opt-in acceptance suites.

## Risks

- Secret-boundary tests can become brittle if they scan every JSON formatting
  detail instead of named persisted surfaces. Keep assertions targeted to
  forbidden values and required authored expressions.
- Docs edits can become too broad because `docs/features/slurm.md` contains
  future live-design material. Prefer adding an implemented-v6 section and
  labeling deferred sections over rewriting the entire document.
- E2E hardening can overlap integration tests. Keep one representative public
  CLI path and leave low-level matrix coverage in unit/contract/integration
  suites.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/e2e/test_cli_slurm_dry_run.py tests/integration/config/test_cli_run.py tests/integration/pipeline/test_slurm_dry_run_planning.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_slurm_manifest_contract.py tests/contracts/test_cli_run_slurm_contract.py tests/contracts/test_continuation_commands_contract.py tests/contracts/test_diagnostics_preflight_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: first extend tests, then fix concrete failures,
  then update docs, then update metadata/PR body after validation.
- Tests to run with each slice: run the focused e2e/integration SLURM command
  after test edits; run contract tests if schema/output assertions change.
- Decisions the executor must not revisit: v6 is dry-run-only; generated
  afterok scripts use `loom stage-job run`, not `loom stage run`; single-job
  scripts use `loom prepared-run continue`; live scheduler behavior belongs to
  v7.
- Conditions that require stopping for the manager: a secret-boundary failure
  that requires broad persistence redesign, a live scheduler behavior gap, or a
  schema change that would invalidate already-merged Phase 3-5 contracts.

## Refinement And Review Budget Status

- Phase implementation refinement: used locally during the expanded-path
  implementation pass after the new e2e secret-boundary test exposed a
  resolved `oc.env` value in dry-run `plan.json`; fixed by persisting the
  SLURM dry-run plan from the composed config's artifact-safe unresolved
  pipeline view
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-08 in this artifact.
- Final phase execution plan: completed on 2026-05-08 in this artifact.
- Implementation summary: added public CLI e2e hardening for both SLURM
  dry-run modes using a diamond DAG, repeated afterok dry-runs, generated
  manifest/script/log/command inspection, and secret-boundary scanning across
  persisted run artifacts. Updated SLURM dry-run preparation so root `plan.json`
  persists artifact-safe unresolved pipeline data instead of resolved
  environment values. Updated SLURM, CLI, execution, pipeline, and preflight
  docs to describe the implemented v6 dry-run contract and v7-deferred live
  submission handoff.
- Implementation validation: targeted suite passed
  (`UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest
  tests/e2e/test_cli_slurm_dry_run.py tests/integration/config/test_cli_run.py
  tests/integration/pipeline/test_slurm_dry_run_planning.py
  tests/contracts/test_slurm_manifest_contract.py
  tests/contracts/test_cli_run_slurm_contract.py
  tests/contracts/test_continuation_commands_contract.py
  tests/contracts/test_diagnostics_preflight_contract.py`; 26 passed);
  focused Ruff passed for changed Python files; focused Pyright passed for
  changed Python files; `make validate-pr` passed Ruff, Pyright, default tests
  (`833 passed, 15 skipped, 8 deselected`), config-extra tests (`410 passed,
  854 deselected`), and build; `make test-summary` passed with overall `1264
  passed, 11 skipped, 862 deselected`.
- Refinement summary: expanded-path implementation refinement was used locally
  to fix the dry-run plan secret-boundary blocker before PR opening. No
  separate blocker-resolution pass was needed.
- Blocker-resolution summary: pending.
- PR preparation: PR body drafted in
  `docs/phases/slurm-dry-run-hardening-pr-body.md` using final
  `make test-summary` evidence.
- Stack maintenance: pending.
- Remaining blockers: none known.
