# Phase 1 Execution Plan: Diagnostics Foundation And Preflight Core

## Metadata

- Status: draft phase execution plan
- Feature focus: `Local Diagnostics`
- PR title: `Local Diagnostics - Phase 1: Diagnostics Foundation and Preflight Core`
- Branch: `codex/add-diagnostics-preflight-core`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-diagnostics-preflight-core`
- Phase execution plan path: `docs/phases/add-diagnostics-preflight-core.md`
- Full plan: `docs/implementation-plans/implementation-plan-v3.md`
- Source phase: Phase 1 - Diagnostics Foundation And Preflight Core
- Stack predecessor: none
- Base branch: local `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible only when it targets
  `develop` and validation/review/CI gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 2 depends on this branch after its PR is
  open or prepared, validated, and recorded as `pr_open`.
- Plan quality gate: passed on 2026-05-07 by `loom_plan_reviewer`
  confirmation review
- Plan quality gate loop budget: initial review used, plan refinement used,
  confirmation review used
- Draft pass: completed by `loom_phase_planner` on 2026-05-07
- Refine pass: pending because the manager selected the expanded path for new
  public diagnostics APIs, source-tree boundaries, and reusable preflight APIs
- Setup limitations: The local `develop` base is ahead of `origin/develop` by
  `699f6bc docs: refine roadmap planning workflow` and
  `d5b51a5 plan: refine v3 implementation plan`. Direct publication of local
  `develop` was not approved because it would publish the pre-existing workflow
  refinement commit, so this phase starts from local `develop` and no push or
  PR creation occurs in this planning pass.
- Blockers: none known for draft planning; implementation must wait for the
  expanded-path refine pass to complete.

## Objective

Introduce the reusable `loom.diagnostics` package boundary and local preflight
core as public Python APIs, including stable result models, check IDs, group
selection, and local check execution, without adding CLI commands, changing
`loom run`, or persisting preflight reports.

## Full-Plan Context

V3 adds local diagnostics and preflight over the v0 runtime, v1 config
composition, and v2 CLI core. Phase 1 is the API/model foundation: it creates
the public diagnostics layer that later phases will call from `loom preflight`,
`loom run`, `loom status`, `loom logs`, and artifact inspection commands.

Future-phase work must remain out of scope. Phase 2 owns CLI preflight and
`loom run` reuse. Phase 3 owns status/log inspection and any store-owned
stage-discovery facade. Phase 4 owns artifact diagnostics commands and v3
end-to-end diagnostic flows.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: all earlier roadmap phases are merged into
  the local `develop` base assigned by the manager, and the v3 plan quality gate
  is recorded as passed there.
- Retarget/rebase plan after predecessor merge: none for this root phase; PR
  target remains `develop`.
- Branch cleanup constraints: branch can be deleted after squash merge only if
  no successor phase branch depends on it.

## Source Phase Summary

- Goal: add diagnostics package boundaries and local preflight result/check
  models without user-facing diagnostic commands.
- Required scope: `src/loom/diagnostics/` public exports, `docs/structure.md`
  diagnostics target tree and import-boundary guidance, preflight statuses and
  severities, check and overall result models, stable check IDs, group
  selection, non-persistent request APIs, and local check groups for config,
  pipeline, selectors, `RUN_URI`, local artifact store, codec registry, local
  executor, and cheap filesystem/input checks.
- Required checkpoints: keep root imports lightweight, use public lower-layer
  APIs, add only minimal owning-package facades if private access would
  otherwise be required, and keep CLI and `loom run` behavior untouched.
- Acceptance criteria: public Python APIs run full and selected local preflight
  groups; results distinguish `PASS`, `WARN`, `FAIL`, and `SKIP`; results carry
  stable IDs, severities, messages, details, and plain-data serialization;
  unknown groups fail clearly; overall status aggregation is deterministic; no
  default run-store writes occur; lower layers do not import diagnostics; and
  import-boundary tests prove diagnostics imports are cheap and CLI-free.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `loom.config.api`
  exposes lazy config composition/inspection APIs; `loom.pipeline` exposes
  pipeline parsing, validation, status models, and lazy execution access;
  `loom.pipeline.planning` exposes selector models and planning errors;
  `loom.pipeline.stores` exposes local run URI resolution, local run stores,
  local artifact stores, and store errors; `loom.io.codecs.registry` exposes
  the default codec registry; `loom.pipeline.executors` exposes `LocalExecutor`.
- Existing tests or harness behavior: package import-boundary tests under
  `tests/package/test_import_boundaries.py` already use subprocess import
  probes for cheap imports and forbidden layer imports. Unit tests mirror source
  layout under `tests/unit/loom/`, contract tests live under `tests/contracts/`,
  and integration tests use synthetic config and pipeline fixtures under
  `tests/integration/`.
- Import-boundary or dependency constraints: `loom.diagnostics.__init__` may
  expose lightweight result models and request types, but must not import
  `loom.cli`, project packages, config-only optional dependencies during root
  import, stores, executors, or stage modules. Heavier check implementations
  should import lower-layer public APIs inside functions or modules that are not
  pulled in by the package root.

## In-Scope Work

- Add a documented `src/loom/diagnostics/` package with public result/request
  exports and an import-light root.
- Update `docs/structure.md` with the canonical diagnostics target tree, module
  responsibilities, import direction, and import-light expectations.
- Define preflight statuses, severities, check group names, stable check IDs,
  check result models, aggregate preflight result models, and plain-data
  serialization.
- Define non-persistent preflight request APIs for full local checks, selected
  groups, optional `RUN_URI`, and any config/run context needed by later CLI
  reuse.
- Implement public Python preflight runner APIs for local check groups:
  `config`, `pipeline`, `selectors`, `run`, `artifacts`, `codecs`, `executor`,
  and `filesystem`.
- Use public lower-layer APIs for config loading/composition, pipeline parsing
  and validation, selector validation, local `RUN_URI` resolution/path safety,
  local artifact store readiness, codec registry availability, local executor
  availability, and cheap filesystem/input existence checks.
- Add only the narrow owning-package public facade needed if a check cannot be
  implemented without private path or business-logic access.

## Out-of-Scope Work

- `loom preflight`, `loom status`, `loom logs`, or `loom artifacts` CLI
  commands.
- Any change to `loom run` behavior, exit codes, output, or default run URI
  allocation.
- Persisted preflight report files or run-store diagnostics documents.
- Runtime/resource profile models.
- External executor, scheduler, plugin, remote store, credential, subprocess,
  SLURM, container, or policy checks.
- Status/log/artifact inspection facades for persisted runs; those belong to
  later phases.
- Domain-specific checks, schemas, codecs, or project stage imports.

## Assumptions

- Authored configs remain trusted project code; diagnostics may load/compose
  them through existing public config APIs but must not import project stage
  modules during package import.
- The default local preflight group set is `config`, `pipeline`, `selectors`,
  `run`, `artifacts`, `codecs`, `executor`, and `filesystem`.
- `PASS`, `WARN`, `FAIL`, and `SKIP` are the only Phase 1 check statuses.
- Unknown groups are request errors rather than skipped checks.
- A missing optional `RUN_URI` should skip or warn only checks that specifically
  require a run URI, while still allowing general config/pipeline readiness
  checks to run.
- Preflight is best-effort and non-persistent; execution-time validation remains
  authoritative.

## Scope Contract

The public Phase 1 contract is a Python diagnostics API, not a CLI contract.
The API must expose small typed models that convert to plain data suitable for
the existing CLI JSON envelope layer in later phases. Check result fields must
include stable check ID, group, status, severity, message, and details. Overall
results must expose deterministic aggregation: any `FAIL` makes the preflight
fail; otherwise warnings make the aggregate warning status; otherwise all pass
or skipped checks aggregate predictably and are covered in tests.

Stable Phase 1 check IDs include at least `config.load`, `pipeline.graph`,
`selectors.validate`, `run_uri.resolve`, `artifact_store.available`,
`codec_registry.available`, `executor.local`, and `filesystem.input_exists`.
The executor may add narrowly named IDs inside the assigned groups only when
tests lock the contract and the names remain domain-neutral.

No Phase 1 API may write preflight output to the run store by default. Lower
layers must not import `loom.diagnostics`. Diagnostics may depend on public
config, pipeline, planning, execution, store, artifact, codec, executor, and URI
APIs; routine imports that would make `import loom.diagnostics` heavy must be
deferred below the root export surface.

## Design Impact

- Maintainability: centralizes reusable diagnostics models and local preflight
  orchestration outside `loom.cli`, while preserving lower-layer ownership for
  config, pipeline, stores, codecs, artifacts, and executors.
- Extensibility: check groups, stable check IDs, and plain-data result models
  leave room for later executor-specific, remote, policy, catalog, and audit
  checks to be added additively.
- Domain neutrality: checks report generic runtime readiness and local
  filesystem/config conditions without project-specific semantics.
- Source-tree boundaries: documents `loom.diagnostics` as a middle layer that
  may import public lower layers, must not be imported by lower layers, and
  remains independent of `loom.cli`.

## Future Compatibility

- Keep result models additive so later JSON payloads can gain fields without
  breaking Phase 1 contracts.
- Keep group names broad enough for Phase 2 CLI selection and narrow enough to
  avoid mixing unrelated readiness checks.
- Keep `RUN_URI` checks aligned with v2 local `file://` contracts so later
  remote-store work can add schemes without changing local behavior.
- Keep diagnostics root imports cheap so future command registration and help
  output remain import-light.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put reusable preflight logic in `loom.cli`. | It would make later `loom run` reuse and Python API testing harder, and would blur CLI presentation with diagnostics business logic. |
| Put config-aware preflight orchestration inside pipeline internals. | Pipeline internals should not own config composition, run URI, codec, artifact-store, and executor readiness as one cross-cutting concern. |
| Persist preflight reports as run-store documents in Phase 1. | V3 defines preflight as best-effort and non-persistent by default; persisted reports would add schema and staleness contracts before a command exists. |
| Add external executor or remote checks now. | The v3 phase is local-only and must remain testable without network, schedulers, containers, plugins, or external services. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local-only best-effort checks do not cover runtime/resource profiles or external backends. | Roadmap v3 deliberately limits diagnostics to local readiness over existing v0-v2 APIs. | Revisit when v4+ runtime/resource/executor surfaces or remote-store requirements land. |
| Diagnostics JSON-compatible models are not persisted schemas. | Phase 1 prepares plain data for later CLI envelopes but does not create a diagnostics database or report files. | Revisit if catalogs, bundles, dashboards, or audit reports need durable diagnostics records. |

## Reviewability

- Expected PR size and shape: one API/model/check-runner PR plus focused tests
  and `docs/structure.md` updates; no CLI output churn.
- Files and areas to inspect: `src/loom/diagnostics/`, any narrow public facade
  added in an owning lower-layer package, `docs/structure.md`,
  `tests/package/`, `tests/unit/loom/diagnostics/`, `tests/contracts/`, and
  `tests/integration/diagnostics/` or the closest existing integration layout.
- Scope-control checks: confirm no CLI command changes, no `loom run` behavior
  changes, no persisted preflight report writes, no project imports, no private
  store path traversal, and no future-phase status/log/artifact inspection.

## Implementation Steps

1. Add the diagnostics package skeleton, lightweight public exports, result
   enums/models, group constants, stable check ID definitions, and plain-data
   serialization.
2. Add preflight request and group-selection APIs, including clear failures for
   unknown groups and deterministic aggregate status behavior.
3. Implement local check runner slices for config, pipeline, selectors, `RUN_URI`
   resolution/path safety, local artifact store, codec registry, local executor,
   and cheap filesystem/input checks using public lower-layer APIs.
4. Add any minimal owning-package public facade that is required to avoid
   diagnostics reaching into private path or business logic, with tests in the
   owning package.
5. Update `docs/structure.md` with the diagnostics source-tree boundary,
   responsibility, import direction, and import-light expectations.
6. Add package, unit, contract, and integration tests, keeping e2e and opt-in
   suites explicitly deferred for this phase.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_import_boundaries.py`, and any new
  `tests/package/test_diagnostics_api.py`.
- Required assertions or deferral reason: public `loom.diagnostics` imports
  expose the intended model/request/runner symbols; `import loom.diagnostics`
  does not import `loom.cli`, stores, executors, project modules, or config-only
  optional dependencies eagerly; lower-layer packages do not import
  `loom.diagnostics`; `docs/structure.md` documents the diagnostics package
  target tree and boundary.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/diagnostics/`.
- Required assertions or deferral reason: status/severity validation, check ID
  stability, result model construction, details normalization to plain data,
  group selection, unknown group errors, aggregate status rules, request
  normalization, and strict-warning helper behavior if implemented in core.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_diagnostics_preflight_contract.py` or a
  similarly named diagnostics contract module.
- Required assertions or deferral reason: check-result and preflight-result
  plain-data schemas are stable; required fields and status/severity values are
  present; stable check IDs remain stable; serialization is suitable for later
  CLI JSON envelopes without object leakage.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/` or focused modules under the
  existing integration layout.
- Required assertions or deferral reason: synthetic local configs exercise
  config load, pipeline graph validation, selector validation, `RUN_URI`
  resolution, local artifact store availability, codec registry availability,
  local executor availability, and cheap filesystem/input checks; selected group
  runs only selected checks; no preflight report is written to a local run store
  by default.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 1 has no user-facing CLI
  diagnostics command and does not change `loom run`; e2e coverage begins when
  Phase 2 exposes CLI preflight and run reuse.

### Opt-In Suites

- Status: deferred
- Markers affected: none.
- Required assertions or deferral reason: Phase 1 adds local-only public Python
  APIs and must not depend on opt-in external services, schedulers, containers,
  plugins, network access, or remote stores.

## Risks

- Import-light regressions could make `loom.diagnostics` pull in config
  optional dependencies, stores, executors, CLI modules, or project stage
  modules too early.
- Result model names, check IDs, and group names become public contracts in
  this phase, so casual renames later would break CLI and automation tests.
- Local preflight can drift into a parallel runtime validator; the executor must
  keep checks best-effort and reuse existing lower-layer validation.
- `RUN_URI` path-safety checks can accidentally write or reserve directories;
  Phase 1 must keep them non-persistent.
- Adding lower-layer facades in this phase can expand scope; add only the
  smallest public facade needed to avoid private access.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py -m package
uv run pytest tests/unit/loom/diagnostics
uv run pytest tests/contracts/test_diagnostics_preflight_contract.py
uv run pytest tests/integration/diagnostics
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with models and package exports, then
  request/group selection, then check groups, then docs, then tests.
- Tests to run with each slice: package import tests after exports; unit tests
  after models and selection; targeted integration tests after check groups;
  contract tests after serialization stabilizes.
- Decisions the executor must not revisit: no CLI commands, no `loom run`
  behavior changes, no persisted reports, local-only check scope, stable group
  names and check IDs, and import-light root diagnostics exports.
- Conditions that require stopping for the manager: a required check needs
  broad lower-layer API redesign, a private store layout dependency appears
  unavoidable, import-light constraints conflict with public exports, or
  validation reveals a need to change Phase 2+ scope.
- Expanded-path refinement notes: the refine pass should verify the public
  model names, aggregate status semantics, selected-group behavior, and
  lower-layer facade needs before implementation begins.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed on 2026-05-07 by `loom_phase_planner`; committed as
  `plan: add phase execution plan`.
- Final phase execution plan: pending expanded-path refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: root phase; no predecessor maintenance pending.
- Remaining blockers: implementation is blocked until the expanded-path refine
  pass completes.
