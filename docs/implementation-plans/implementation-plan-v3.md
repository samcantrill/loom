# Implementation Plan v3: Local Diagnostics And Preflight

## Metadata

- Status: refined implementation plan
- Related planning notes: `docs/implementation-plans/roadmap-v3-planning-notes.md`
- Related brief: none
- Related specifications:
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/pipeline-graph.md`
  - `docs/features/errors.md`
  - `docs/features/testing.md`
- Draft pass: complete
- Refine pass: complete; plan quality gate refinement pass applied on
  2026-05-07
- Plan quality gate: passed on 2026-05-07 by `loom_plan_reviewer`
  confirmation review
- Blockers: none known

## Goal

Implement `loom` v3 as the local diagnostics and preflight layer over the v0
runtime kernel, v1 config composition, and v2 CLI core.

The v3 target is a domain-neutral diagnostics surface that lets local terminal
users check a config and local environment before execution, then inspect run
status, stage logs, and recorded artifact metadata after execution without
manually reading the run-store layout.

## Context

The roadmap defines v3 as "Local diagnostics and preflight":

- Preflight result models, check result models, stable statuses, severities,
  check IDs, and JSON output.
- Config, pipeline graph, selector, `run_uri`, resolved local run-store path,
  local artifact store, codec registry, local executor, and cheap local
  filesystem checks.
- Minimal preflight subset reused by `loom run` for config load, graph
  validation, `run_uri`/resolved path safety, and executor resolution.
- `loom preflight CONFIG`.
- `loom status RUN_URI`.
- `loom logs RUN_URI STAGE`.
- `loom artifacts list RUN_URI`.
- `loom artifacts show RUN_URI ARTIFACT_ID`.
- Golden-output tests where useful and synthetic end-to-end tests for failed
  and successful local runs.

V2 is complete and exposes the command framework, `--format text|json`, JSON
envelope helpers, local `file://` `run_uri` behavior, and functional
`validate`, `plan`, and `run` commands. Current store and execution APIs expose
local run status, stage status, failures, logs, events, artifact indexes, and
run URI resolution helpers that v3 should read through public facades instead
of by duplicating private path logic in `loom.cli`.

## Desired Outcome

After v3 is complete:

- A user can run explicit local preflight diagnostics for a config before
  execution.
- Explicit preflight can report pass, warning, failure, and skipped checks with
  stable check IDs and machine-readable JSON.
- `loom run` reuses a minimal non-persistent preflight subset before execution
  without replacing runtime validation.
- A user can inspect a local run with `loom status RUN_URI`.
- A user can inspect stage logs with `loom logs RUN_URI STAGE`, including
  resolved log paths and bounded content display.
- A user can list and show recorded artifact metadata with
  `loom artifacts list RUN_URI` and
  `loom artifacts show RUN_URI ARTIFACT_ID`.
- Successful and failed local runs can be diagnosed end to end through compact
  CLI text output.
- Automation-facing diagnostics expose stable JSON envelopes using the existing
  v2 CLI conventions.
- Reusable diagnostics logic lives outside `loom.cli` and depends only on
  public lower-layer APIs.

## Non-Goals

- No runtime/resource profile models. Those belong to v4.
- No subprocess, SLURM, plugin, remote credential, container, or scheduler
  checks.
- No scheduler or live job status in `loom status`.
- No live log following or unbounded log tailing.
- No artifact payload display, artifact `cat`, or checksum verification.
- No persisted standalone preflight report files by default.
- No run catalog, comparison, bundle export/import, sweeps, cleanup, retention,
  dashboards, or remote run URI schemes.
- No new domain-specific commands, schemas, codecs, or stage imports.
- No new heavyweight runtime dependencies for diagnostics or terminal
  rendering.

## Constraints

- Preserve `loom` as a domain-neutral runtime.
- Preserve the import boundaries in `docs/structure.md`: CLI remains the outer
  layer, and lower-level packages must not import `loom.cli`.
- Keep public imports cheap and avoid loading project stage modules during
  diagnostics command registration, top-level help, or package import.
- Treat authored configs as trusted project code.
- Use public Python APIs from config, pipeline, planning, execution, stores,
  artifacts, and codecs instead of walking private file layout in CLI modules.
- Keep v2 `run_uri` as the public run-addressing contract for v3 diagnostics.
- Keep v3 local-only and testable without SLURM, Docker, Apptainer, cloud
  services, network access, or project-specific stage imports.
- Use `--format text|json` for v3 command output, reusing v2 JSON envelope
  conventions rather than adding a separate `--json` flag.
- Run `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.

## Design Principles

- Diagnostics should expose what the runtime already knows; they should not
  create a parallel model of config composition, planning, stores, artifacts, or
  execution.
- Human output should be compact, stable, and oriented around the debugging
  question a terminal user is asking.
- Machine output should be plain data with stable check IDs, statuses, and JSON
  envelope schema versions suitable for tests and simple automation.
- Preflight is best-effort and non-persistent by default. Execution must still
  validate critical assumptions when it acts.
- Local diagnostics should be useful without optional executors, plugins,
  remote stores, external commands, or project imports.
- New public result models should be small and composable so later catalog,
  remote-store, executor, and reliability work can extend them without changing
  the v3 defaults.

## Key Design Choices

- Add a reusable `loom.diagnostics` package as the middle layer between runtime
  APIs and `loom.cli`. It may import public config, pipeline, planning,
  execution, store, artifact, codec, executor, and URI APIs. Those lower layers
  should not import `loom.diagnostics`.
- Keep `import loom.diagnostics` cheap. The package `__init__` should expose
  lightweight result models and request types without loading project stage
  modules, command registration, config composition, local store construction, or
  executor implementations. Checks that need heavier public APIs should import
  those APIs inside the specific check implementation.
- Keep CLI modules thin: parse arguments, call diagnostics APIs, format
  results, and return exit codes.
- Use `RUN_URI` for all v3 diagnostics command arguments. Plain local paths and
  old `RUN_DIR` terminology are not public v3 inputs.
- Reuse `--format text|json`; roadmap references to `--json` are fulfilled by
  `--format json`.
- `loom preflight CONFIG` accepts optional `--run-uri RUN_URI`, repeatable
  `--check GROUP`, `--strict`, and `--format text|json`.
- Preflight groups are `config`, `pipeline`, `selectors`, `run`, `artifacts`,
  `codecs`, `executor`, and `filesystem`; the default is all local groups.
- Preflight check results use `PASS`, `WARN`, `FAIL`, and `SKIP` statuses and
  stable check IDs such as `config.load`, `pipeline.graph`,
  `selectors.validate`, `run_uri.resolve`, `artifact_store.available`,
  `codec_registry.available`, `executor.local`, and `filesystem.input_exists`.
- `loom run` reuses a minimal diagnostics subset for config load, graph
  validation, `run_uri`/resolved path safety, and executor resolution. This
  reuse should call shared diagnostics logic, not duplicate checks in
  `loom.cli.run`. When `loom run` omits `--run-uri`, Phase 2 must allocate the
  implicit local `RUN_URI` once before preflight and pass the same URI to
  execution.
- `loom status RUN_URI` reads persisted local run state only: run status, stage
  table, failure summaries, log path hints, artifact counts, and available
  provenance summaries.
- Status/log diagnostics must use a store-owned stage-discovery and run-state
  inspection facade when the caller does not already know every stage name. The
  facade belongs in `loom.pipeline.stores`, not in `loom.cli` or path-walking
  diagnostics code.
- `loom logs RUN_URI STAGE` uses `--stream stdout|stderr|both`, `--tail N`,
  `--paths`, and `--format text|json`. The default is bounded content display
  with resolved paths; `--paths` suppresses content. `--follow` and unbounded
  tailing are deferred.
- `loom artifacts list RUN_URI` and
  `loom artifacts show RUN_URI ARTIFACT_ID` are metadata/provenance-only and do
  not load artifact payloads.

## Conflicts And Tradeoffs

- API-foundation reviewability vs immediate CLI-visible value: Phase 1 is kept
  separate so result models, check grouping, and preflight core behavior can be
  reviewed before command output is layered on top.
- Local terminal ergonomics vs future remote stores: v3 requires `RUN_URI`
  rather than plain paths so diagnostics stay aligned with v2 and later remote
  store work.
- Best-effort preflight vs durable audit trail: v3 keeps preflight
  non-persistent because checks can become stale and may run before a run
  exists. Users who need records can save JSON output externally.
- Thin CLI vs convenient status aggregation: v3 introduces diagnostics facades
  so CLI code can format summaries without walking private store paths.
- Compact text vs automation stability: text output is optimized for local
  debugging, while JSON output remains structured and schema-versioned for
  tests and simple automation.
- Bounded log display vs full terminal tooling: v3 provides enough log content
  to debug common local failures and defers live follow or unbounded reads until
  subprocess/scheduler execution creates stronger requirements.

## Maintainability Assessment

The plan keeps maintainability centered on ownership boundaries. Diagnostics
models and aggregation live in `loom.diagnostics`; CLI modules remain
presentation and exit-code layers; config, planning, stores, artifacts, codecs,
and execution keep their existing responsibilities. Separating preflight core,
preflight CLI reuse, status/logs, and artifacts into four phases keeps each PR
reviewable by behavior cluster and avoids mixing model design with every command
surface at once.

The main maintainability risk is letting `loom.diagnostics` become a broad
pass-through package. Phase plans should add diagnostics facades only when they
remove CLI-local business logic or provide a reusable Python result model.
Lower-level public facades should be added in the owning package if diagnostics
would otherwise need private file layout or internal planning details.
Phase 1 must also update `docs/structure.md` so the new diagnostics package is
part of the canonical source-tree boundary rather than an undocumented exception.

## Extensibility Assessment

V3 establishes extension points that later roadmap versions can build on:

- Preflight groups and stable check IDs can grow executor-specific, remote
  store, plugin, container, and policy checks without changing the explicit
  preflight command shape.
- Status summaries can later include catalog, remote-store, executor, retry, or
  cleanup state while preserving the v3 local persisted-state default.
- Log summaries can later add follow behavior, subprocess attempt metadata, or
  scheduler hints without changing the basic `RUN_URI STAGE` command.
- Artifact metadata summaries can later support checksum verification, payload
  display, bundle export, and catalog indexing as opt-in operations.

V3 deliberately does not add schema migrations or remote addressing semantics.
Future compatibility depends on keeping v3 JSON payloads plain, versioned, and
small enough to evolve additively.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Preflight remains best-effort, local-only, and non-persistent. | Roadmap defers runtime profiles, external executors, remote stores, policy files, and durable audit records. | Revisit when v4+ runtime/resource/executor surfaces or audit-policy requirements land. |
| `loom run` only reuses a minimal preflight subset. | Runtime validation remains authoritative, and broad preflight checks may be stale or too noisy for every run. | Revisit when run options and policy files define which checks are required at execution time. |
| Log display is bounded and does not follow live updates. | V3 targets local debugging over persisted logs; live process control belongs to later subprocess/scheduler phases. | Revisit in v5+ when stage-worker and executor logs introduce live attempts. |
| Artifact commands inspect metadata/provenance only. | Payload display and checksum verification need explicit codec, size, and trust policies. | Revisit when an artifact payload or verification command is explicitly planned. |
| Diagnostics JSON schemas are CLI output contracts, not persisted records. | V3 does not add a diagnostics database or persisted preflight schema. | Revisit if catalogs, bundles, dashboards, or audit reports need durable diagnostics documents. |

## Plan Quality Gate

- Status: passed on 2026-05-07 by `loom_plan_reviewer` confirmation review
- Required reviewer: `loom_plan_reviewer`
- Required before: creating any v3 phase execution plan or starting Phase 1
  implementation
- Loop budget:
  - Initial review: used on 2026-05-07.
  - Refinement pass: used on 2026-05-07.
  - Confirmation review: used on 2026-05-07.
- Review focus:
  - maintainability of the `loom.diagnostics` package boundary;
  - extensibility of preflight check groups and result models;
  - compatibility with v2 `run_uri` and CLI envelope conventions;
  - avoidance of private run-store path traversal in `loom.cli`;
  - sufficiency of per-phase package, unit, contract, integration, e2e, and
    opt-in test expectations;
  - reviewability of each phase as one PR.
- Initial review findings addressed:
  - Phase 1 now requires updating `docs/structure.md` with the canonical
    diagnostics package boundary, import direction, responsibility, and
    import-light expectations.
  - Phase 3 now requires a narrow store-owned stage-discovery/run-state
    inspection facade before diagnostics aggregation.
  - Phase 2 now pins default `loom run` URI preflight behavior to a single
    allocation before preflight and execution, with focused tests.
- Confirmation review result: no blocking findings remain; Phase 1 execution
  planning may start.
- Current gate result: passed and approved for phase implementation.

### Plan Refinement Summary

| Original finding | Change made | Location |
| --- | --- | --- |
| `loom.diagnostics` was not tied back to canonical source-tree documentation. | Added import-light package expectations and made Phase 1 update `docs/structure.md` as an explicit scope item, acceptance criterion, and package-suite obligation. | Key Design Choices; Maintainability Assessment; Phase 1 Scope, Acceptance Criteria, Test expectations, Design impact |
| Phase 3 could require status tables without any public way to discover stages. | Added a store-owned stage-discovery/run-state inspection facade to Phase 3 scope, acceptance criteria, contract tests, and integration tests. | Key Design Choices; Phase 3 Scope, Acceptance Criteria, Test expectations, Design impact |
| Default `loom run` preflight could check a different path than execution. | Pinned the planned behavior to allocate the implicit `RUN_URI` once before preflight and pass that same URI into execution, with tests for the default-run case. | Key Design Choices; Phase 2 Scope, Acceptance Criteria, Test expectations |

Accepted risks remain the v3-local debts recorded in the technical debt ledger:
best-effort non-persistent preflight, minimal run preflight, bounded log display,
metadata-only artifact inspection, and CLI JSON schemas as output contracts
rather than persisted records.

## Phased Implementation

### Phase 1 - Diagnostics Foundation And Preflight Core

Status: merged
Branch: `codex/add-diagnostics-preflight-core`
PR: https://github.com/samcantrill/loom/pull/65 (merged);
blocker-resolution follow-up:
https://github.com/samcantrill/loom/pull/66 (merged)

Goal:

- Introduce the reusable diagnostics package and local preflight result/check
  model without adding user-facing diagnostic commands yet.

Scope:

- Add `src/loom/diagnostics/` package boundaries and public exports.
- Update `docs/structure.md` with the canonical `loom.diagnostics` target tree,
  import direction, module responsibility, and import-light expectations.
- Add preflight statuses, severities, check result models, overall result
  model, stable check IDs, group selection, and non-persistent preflight request
  APIs.
- Implement the local check runner and local check groups for config, pipeline,
  selectors, `RUN_URI`, local artifact store, codec registry, local executor,
  and cheap filesystem/input checks as public Python APIs.
- Ensure preflight results serialize to plain data suitable for JSON envelopes.
- Keep the runner reusable by both `loom preflight` and the `loom run` command
  path.
- Add only the minimal owning-package public facades needed to avoid private
  path or business-logic access from diagnostics.

Out of scope:

- CLI `preflight`, `status`, `logs`, or `artifacts` commands.
- Changes to `loom run` behavior.
- Persisted preflight reports.
- Runtime/resource profiles.
- External executor, scheduler, plugin, remote, or container checks.

Acceptance criteria:

- Public Python APIs can run the full local preflight set and selected check
  groups against synthetic local configs.
- Results distinguish `PASS`, `WARN`, `FAIL`, and `SKIP`.
- Results carry stable check IDs, severities, messages, details, and plain-data
  serialization.
- Unknown check groups fail clearly.
- Overall status aggregation is deterministic and documented in tests.
- No preflight result is written to the run store by default.
- Lower-level packages do not import `loom.diagnostics`.
- `docs/structure.md` documents the new diagnostics package boundary and states
  that root diagnostics imports remain lightweight.
- Import-boundary tests prove `import loom.diagnostics` does not import
  `loom.cli` or eagerly construct local stores, executors, or project stage
  modules.

Test expectations:

- Package: public import, import-light, and import-boundary tests for
  `loom.diagnostics`, including lower layers not importing diagnostics.
- Unit: result model validation, group selection, status aggregation, check ID
  stability, strict warning helpers if implemented in core.
- Contract: plain-data serialization and stable check-result schema contracts.
- Integration: config, graph, selector, `RUN_URI`, local store, codec, executor,
  and filesystem checks using synthetic fixtures.
- E2E: not required in this phase.
- Opt-in: none.

Design impact:

- Adds a new middle-layer package that depends on public config, pipeline,
  planning, store, artifact, codec, executor, and URI APIs while remaining
  independent of `loom.cli`.
- Updates the canonical source-tree map so diagnostics ownership is reviewable
  as part of the package boundary instead of living only in implementation-plan
  prose.

Future compatibility:

- Check groups and check IDs should allow later executor-specific, remote, and
  policy checks without hard dependencies in v3.

Alternatives rejected:

- Putting reusable preflight logic in `loom.cli`.
- Putting config-aware preflight orchestration inside pipeline internals.
- Persisting preflight reports as first-class run-store documents in v3.

Debt introduced:

- Local-only best-effort checks do not cover future runtime/resource profiles
  or external backends.

Reviewability:

- Review as one API/model/check-runner PR without CLI output churn.

Notes:

- PR feature focus: `Local Diagnostics`
- Intended PR title: `Local Diagnostics - Phase 1: Diagnostics Foundation and Preflight Core`
- Phase implementation refinement budget: used on 2026-05-07 by
  `loom_phase_refiner`; no code changes were needed in the automated refinement
  pass.
- Phase PR review budget: used on 2026-05-07 by `loom_phase_reviewer`; one
  blocking suite-marker finding was resolved in the user-authorized
  blocker-resolution follow-up PR.

Completion summary:

- Merged by https://github.com/samcantrill/loom/pull/65 on 2026-05-06 with
  merge commit `be74982b3be96fe7bee77f5e1fb501148e236d21`.
- Added import-light `loom.diagnostics` public exports, preflight
  status/severity/group/request/result models, stable Phase 1 check IDs,
  deterministic group selection and aggregation, local preflight checks, and
  plain-data serialization.
- Updated `docs/structure.md` with the diagnostics package boundary and added
  package, unit, contract, and integration coverage for the Phase 1 public API.
- Blocker-resolution follow-up
  https://github.com/samcantrill/loom/pull/66 merged on 2026-05-07 with merge
  commit `bc0b7bc4367f1e2498596f6744cd892718392ba0`; it added the
  `optional_dependency` marker so diagnostics integration tests are collected
  by the config-extra gate and refreshed Phase 1 evidence docs.
- Final validation for the blocker-resolution branch passed:
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`,
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary`, and GitHub CI for PR #66.

### Phase 2 - Preflight CLI And Run Reuse

Status: pending
Branch: `codex/add-preflight-cli`
PR: pending

Goal:

- Expose preflight diagnostics through the CLI and reuse the minimal local
  preflight subset before `loom run` execution.

Scope:

- Add `loom preflight CONFIG`.
- Support `--format text|json`, `--strict`, optional `--run-uri RUN_URI`, and
  repeatable `--check GROUP`.
- Format compact human preflight output and stable JSON envelopes through
  existing CLI helpers.
- Reuse the Phase 1 diagnostics runner for the explicit command.
- Reuse a minimal non-persistent preflight subset in `loom run` for config
  load, graph validation, `RUN_URI`/resolved path safety, and executor
  resolution.
- For `loom run` without `--run-uri`, allocate the implicit local `RUN_URI`
  once before the minimal preflight subset and pass that same URI into
  `RunRequest`; this keeps preflight path checks and execution aligned without
  writing run-store records before execution.
- Map preflight failures and strict warnings to existing CLI exit-code policy.
- Add help text that makes preflight best-effort and non-persistent.

Out of scope:

- `status`, `logs`, or `artifacts` commands.
- Persisted preflight reports.
- External executor checks and policy files.
- Runtime/resource profile options.
- Replacing execution-time validation with preflight.

Acceptance criteria:

- Users can run explicit local preflight before execution.
- `--strict` fails when warnings are present.
- `--check` limits the run to selected local groups and rejects unknown groups.
- `--run-uri` enables run-specific path safety checks; omitting it still checks
  general local readiness.
- Text output is compact and includes check statuses, IDs, and messages.
- JSON output uses v2 envelope conventions and a stable diagnostics payload.
- `loom run` reuses the minimal subset without duplicating preflight logic in
  CLI code.
- `loom run` default URI behavior is deterministic: the URI checked by minimal
  preflight is the URI passed into execution, and a focused test covers the
  omitted-`--run-uri` case.
- Preflight warnings or failures do not create run-store records.

Test expectations:

- Package: CLI import-light checks remain passing.
- Unit: parser/options, text formatting, JSON payload shape, strict exit-code
  mapping, selected-group behavior, run command preflight hook behavior, and
  default `loom run` URI allocation before preflight.
- Contract: CLI result envelope compatibility with v2 conventions.
- Integration: preflight command against synthetic valid, warning, and invalid
  configs; run command minimal preflight failure cases.
- E2E: one successful local preflight and one failing local preflight through
  `main(argv)`.
- Opt-in: none.

Design impact:

- Extends the v2 CLI command surface while preserving `--format text|json`,
  thin CLI orchestration, and non-persistent diagnostics.

Future compatibility:

- The check group interface can grow with v4+ runtime options and later
  executor families.

Alternatives rejected:

- Adding a separate `--json` flag for preflight.
- Recomputing preflight checks directly inside `loom.cli.run`.
- Making explicit preflight require a `RUN_URI`.
- Letting default `loom run` preflight skip path safety while the runner later
  allocates an unchecked URI.

Debt introduced:

- Minimal `loom run` preflight is a safety screen, not a durable audit log or a
  substitute for runtime validation.

Reviewability:

- Review as one CLI integration PR with narrow behavior and command tests.

Notes:

- PR feature focus: `Local Diagnostics`
- Intended PR title: `Local Diagnostics - Phase 2: Preflight CLI and Run Reuse`
- Phase implementation refinement budget: unused
- Phase PR review budget: unused

Completion summary:

- Pending.

### Phase 3 - Status And Logs Inspection

Status: pending
Branch: `codex/add-status-logs-diagnostics`
PR: pending

Goal:

- Let users inspect local run status and stage logs through CLI commands backed
  by reusable diagnostics inspection facades.

Scope:

- Add a narrow store-owned inspection facade for stage discovery and run-state
  aggregation before diagnostics uses it, such as `list_stages` plus a
  stage-state bundle or `scan_run_state` in `loom.pipeline.stores`.
- Add diagnostics result models/facades for persisted run status, stage status
  tables, failure summaries, artifact counts, log path hints, and available
  provenance summaries.
- Add diagnostics result models/facades for stage log path lookup and bounded
  content display.
- Add `loom status RUN_URI` with text and JSON output.
- Add `loom logs RUN_URI STAGE` with text and JSON output.
- Support `loom logs` options:
  - `--stream stdout|stderr|both`, default `both`;
  - `--tail N`, default bounded line count selected in the phase plan;
  - `--paths`, to show resolved paths without content;
  - `--format text|json`.
- Add tests for successful runs, failed runs, missing runs, missing stages,
  missing logs, and corrupt store documents where practical.

Out of scope:

- Scheduler or job status.
- Live log following and unbounded tailing.
- Artifact list/show commands.
- Stage-worker attempt commands.
- Run catalog or comparison behavior.

Acceptance criteria:

- A successful local run and a failed local run can be summarized without
  importing project stage modules.
- Status output includes run status, stage table, failure summaries, log path
  hints, and artifact counts.
- Failed stage summaries include useful failure and log path hints.
- Logs display resolved stdout/stderr paths and bounded content through public
  store APIs.
- Diagnostics and CLI code discover stages through the store-owned inspection
  facade rather than globbing private `stages/*` layout paths.
- Corrupt, missing, or partially written stage documents produce clear
  diagnostics behavior through the inspection facade.
- Missing logs and missing stages fail clearly.
- JSON output uses stable CLI envelopes and plain-data diagnostics payloads.

Test expectations:

- Package: import boundaries prevent lower layers from importing CLI or
  diagnostics incorrectly.
- Unit: status/log summary models, formatting, stream selection, bounded content
  handling, and error mapping.
- Contract: store protocol tests cover the new stage-discovery/run-state
  inspection facade, and diagnostics facades read through that facade rather
  than private paths.
- Integration: local run-store fixtures for success, failure, stage discovery,
  missing stage, missing log, and corrupt-document cases.
- E2E: `loom status` and `loom logs` over synthetic successful and failed local
  runs.
- Opt-in: none.

Design impact:

- Adds reusable run inspection APIs that CLI and future tools can call without
  shelling out or importing project code.
- Extends `loom.pipeline.stores` with narrow read-only recovery helpers before
  diagnostics aggregation, preserving store ownership of local run layout.

Future compatibility:

- Status summaries should leave room for later catalog, remote store,
  executor-specific, retry, and cleanup fields without querying those systems
  in v3.
- Log summaries should leave room for later attempt-aware and live-follow
  behavior.

Alternatives rejected:

- Direct CLI traversal of local run-store file paths.
- Direct diagnostics traversal of local run-store file paths when the store does
  not already expose stage discovery.
- Scheduler/job queries in the general status command.
- Implementing `--follow` before subprocess or scheduler execution exists.

Debt introduced:

- Bounded log display is intentionally simpler than tail/follow behavior.

Reviewability:

- Review as one post-run inspection PR focused on run state and logs.

Notes:

- PR feature focus: `Local Diagnostics`
- Intended PR title: `Local Diagnostics - Phase 3: Status and Logs Inspection`
- Phase implementation refinement budget: unused
- Phase PR review budget: unused

Completion summary:

- Pending.

### Phase 4 - Artifact Inspection And End-To-End Diagnostics

Status: pending
Branch: `codex/add-artifact-diagnostics`
PR: pending

Goal:

- Complete v3 local diagnostics by exposing artifact metadata inspection and
  proving the full preflight-run-status-logs-artifacts workflow.

Scope:

- Add artifact diagnostics result models/facades over run-store artifact
  indexes, `ArtifactRef` metadata, producer information, and available generic
  provenance.
- Add `loom artifacts list RUN_URI` with text and JSON output.
- Add `loom artifacts show RUN_URI ARTIFACT_ID` with text and JSON output.
- Add end-to-end tests covering successful and failed local diagnostic flows.
- Add or update compact golden-output tests where stable and useful.
- Update user-facing docs or README snippets if the phase plan identifies a
  minimal diagnostics quickstart as reviewable in scope.

Out of scope:

- Artifact payload `cat`.
- Artifact checksum verification.
- Artifact content loading through codecs.
- Run catalog, comparison, export/import, retention, or cleanup.

Acceptance criteria:

- Users can list recorded artifacts without loading payloads.
- Users can inspect one artifact's metadata and generic provenance without
  loading payloads.
- Missing artifact IDs fail clearly.
- Successful and failed local runs can be diagnosed end to end through CLI text
  output.
- JSON output remains stable for automation-facing diagnostics.
- The final v3 workflow uses public diagnostics and store APIs rather than
  private run-layout traversal in CLI modules.

Test expectations:

- Package: public artifact diagnostics imports are stable and import-light.
- Unit: artifact summary models, text formatting, JSON payload conversion, and
  missing-artifact error mapping.
- Contract: artifact diagnostics read `ArtifactRef` metadata through public
  run-store APIs.
- Integration: artifact list/show over local run-store fixtures with multiple
  stages and artifact types.
- E2E: full local workflow using `preflight`, `run`, `status`, `logs`, and
  `artifacts` over successful and failed synthetic runs.
- Opt-in: none.

Design impact:

- Completes the v3 local diagnostics surface without adding domain artifact
  semantics.

Future compatibility:

- Artifact summaries should allow later checksum verification, payload display,
  bundle export, and catalog indexing to build on metadata without changing the
  v3 default behavior.

Alternatives rejected:

- Reading artifact payloads by default.
- Adding checksum verification before an explicit opt-in policy exists.
- Implementing artifact catalog or comparison behavior in v3.

Debt introduced:

- Artifact inspection remains metadata/provenance-only until a later command
  defines payload and checksum policies.

Reviewability:

- Review as one artifact-focused PR plus end-to-end diagnostic evidence.

Notes:

- PR feature focus: `Local Diagnostics`
- Intended PR title: `Local Diagnostics - Phase 4: Artifact Inspection and End-to-End Diagnostics`
- Phase implementation refinement budget: unused
- Phase PR review budget: unused

Completion summary:

- Pending.
