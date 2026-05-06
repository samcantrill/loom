# Roadmap v3 Planning Notes: Local Diagnostics And Preflight

## Metadata

- Roadmap version: v3
- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`
- Previous version status: v2 implementation plan records all phases as merged.
- Planning notes status: ready for implementation-plan drafting
- Current discussion stage: complete
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Practical design refinement: confirmed
  - Phase shaping: confirmed
  - Handoff: confirmed
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v2.md`
- Related feature docs:
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/pipeline-graph.md`
  - `docs/features/errors.md`
  - `docs/features/testing.md`
- Blockers: none

## Roadmap Extraction

Baseline roadmap outcome:

- Give users reliable local diagnostics before and after execution without
  requiring manual inspection of run files.
- Add preflight result models, check result models, stable statuses, severities,
  check IDs, and JSON output.
- Add config, pipeline graph, selector, `run_uri`, resolved local run-store
  path, local artifact store, codec registry, local executor, and local
  filesystem checks.
- Reuse a minimal preflight subset from `loom run` for config load, graph
  validation, `run_uri` and resolved local path safety, and executor
  resolution.
- Add local diagnostics commands for preflight, run status, stage logs, and
  artifact inspection.

Prerequisites:

- v0 local runtime kernel: local Python APIs, local run store, artifact store,
  static pipeline graph, local execution, provenance, resume, and inspectable
  run layout.
- v1 config composition: recursive includes, replacements, strict overrides,
  source snapshots, and composition provenance through public APIs.
- v2 CLI core: `argparse` command framework, shared CLI formatting/error
  helpers, `loom validate`, `loom plan`, `loom run`, local `file://` `run_uri`
  support, and JSON envelope conventions.
- Public store and artifact inspection facades must exist or be added in their
  owning packages before CLI commands depend on them.

Primary feature docs:

- `preflight.md`
- `cli.md`
- `run-store.md`
- `artifacts.md`
- `pipeline-graph.md`
- `errors.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Runtime/resource profiles.
- Subprocess, SLURM, plugin, remote credential, and container checks.
- Large checksum scans.
- Preflight policy files.
- Scheduler job status integration.
- Log following unless deliberately selected for this version.
- Artifact payload reading or arbitrary artifact content display.
- Artifact checksum verification.
- Run catalog, comparison, bundle export/import, sweeps, cleanup, retention,
  dashboards, and remote run URI schemes.

Compatibility obligations:

- Preserve v2 CLI import-light behavior and keep CLI modules as the outermost
  layer.
- Use public Python APIs from config, pipeline, planning, execution, stores,
  artifacts, and codecs instead of duplicating business logic in `loom.cli`.
- Keep v2 `run_uri` as the public run-addressing contract for v3 diagnostics.
- Keep local v3 behavior domain-neutral and testable without SLURM, Docker,
  Apptainer, cloud services, network access, or project-specific stage imports.
- Keep human output compact and JSON output stable enough for tests and simple
  automation.
- Avoid new heavyweight runtime dependencies.

## User Intent

Target audience:

- Local terminal users debugging or validating single-run `loom` pipelines.

User-visible outcome:

- After v3, a user can run a local preflight check, execute a local run,
  inspect status, view stage logs, and inspect recorded artifacts through
  stable CLI commands.
- Human local debugging is the primary optimization target. JSON output remains
  stable for commands intended for automation, but automation is not the first
  design driver.
- Functional benefit framing: v2 lets users validate, plan, and run a local
  pipeline; v3 lets them answer the operational follow-up questions without
  knowing the run-store file layout:
  - Will this config and local environment probably work before I run it?
  - What happened in this run?
  - Which stage failed or is blocked?
  - Where are the logs and what do they say?
  - What artifacts did the run record?
- V3 is therefore a local observability and debugging layer, not a new execution
  capability.

Success criteria:

- V3 includes all four local diagnostics command families: `preflight`,
  `status`, `logs`, and `artifacts`.
- Successful and failed local runs can be diagnosed end to end through CLI text
  output without manual run-file inspection.
- Automation-facing commands expose stable JSON output.
- `loom logs` shows resolved log paths and supports bounded content display.

Non-goals:

- Do not broaden v3 into executor operations, catalogs, sweeps, remote stores,
  containers, or dashboards.
- Do not include live log following or unbounded tailing in the first logs
  surface.
- Do not include scheduler or job status in `loom status`.
- Do not include artifact payload `cat` or checksum verification in v3.

Constraints:

- Preserve `loom` as a domain-neutral runtime.
- Preserve `docs/structure.md` import boundaries.
- Treat authored configs as trusted project code.
- Prefer standard-library CLI machinery and existing local helper APIs.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | v3 is local diagnostics and preflight, not broader operations; target local terminal users debugging single-run pipelines; optimize human local debugging first; use `RUN_URI` for diagnostics and downstream plan language. | JSON output remains stable where commands expose it. | None. | Discover workflows, success criteria, non-goals, constraints, and operational realities. |
| Intent discovery | Include `preflight`, `status`, `logs`, and `artifacts`; done means successful and failed local runs can be diagnosed end to end through CLI text output; stable JSON remains required for automation-facing commands; `loom logs` starts with resolved log paths and bounded content display. | Defer live log following and unbounded tailing. | None. | Sort roadmap capabilities into include, defer, maybe, and out of scope. |
| Feature brainstorming | Include the full local preflight check set: config, pipeline graph, selectors, `RUN_URI` safety, local artifact store, codec registry, local executor, and cheap local filesystem/input checks; `loom status RUN_URI` shows run status, stage table, failure summaries, log path hints, and artifact counts; artifact commands are metadata-only over `ArtifactRef` and provenance. | Include all four command families. | None. | Refine API ownership, CLI surface details, persisted records, failure modes, compatibility, and debt. |
| Practical design refinement | Use `--format text|json`; keep preflight non-persistent by default; keep reusable logic outside `loom.cli`; add a reusable `loom.diagnostics` package between runtime APIs and CLI; `loom preflight CONFIG` accepts optional `--run-uri RUN_URI`; preflight check grouping uses repeatable `--check GROUP` with local groups. | Default preflight group set is all local groups. | None. | Shape the work into reviewable implementation phases. |
| Phase shaping | V3 is accepted as the local observability/debugging layer over v2 local runs; use four phases: diagnostics foundation and preflight core, preflight CLI and run reuse, status/log inspection, artifact inspection and end-to-end diagnostics. | Keep Phase 1 separate for reviewability unless the implementation-plan draft chooses to combine it with Phase 2 for stronger immediate CLI-visible value. | None. | Record handoff inputs and confirm planning notes are ready for implementation-plan drafting. |
| Handoff | Planning notes are ready for the implementation-plan draft prompt; v3 should be drafted as local observability/debugging over v2 local runs with `RUN_URI` diagnostics, non-persistent preflight, reusable `loom.diagnostics`, and the recorded four-phase sketch. | The implementation-plan draft may combine Phase 1 and Phase 2 only if it judges immediate CLI-visible value more important than API-foundation reviewability. | None. | Enter `implementation-plan-draft.md` when requested. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Preflight result and check models | include | Roadmap-owned core surface for stable diagnostics and JSON output. | Should live outside CLI because `loom run` reuses a minimal preflight subset. |
| Preflight check runner | include | Needed by explicit preflight command and minimal `loom run` safety checks. | Scope should start local-only. |
| `loom preflight CONFIG` | include | Main before-run diagnostic command. | Roadmap names `--strict`, `--json`, and local-only check grouping. |
| Minimal `loom run` preflight reuse | include | Prevents run path from diverging from explicit preflight. | Must not replace runtime checks because preflight can become stale. |
| `loom status RUN_URI` | include | Main after-run summary command. | Should read through run-store APIs and avoid project imports. |
| `loom logs RUN_URI STAGE` | include | Failed-run debugging surface. | Include resolved paths and bounded content display; defer live follow and unbounded tailing. |
| `loom artifacts list RUN_URI` | include | Artifact inventory inspection. | Metadata only by default. |
| `loom artifacts show RUN_URI ARTIFACT_ID` | include | Detailed artifact reference/provenance inspection. | Avoid payload loading. |
| Full local preflight check set | include | Confirms the local readiness conditions users need before running. | Covers config, graph, selectors, `RUN_URI` safety, local artifact store, codec registry, local executor, and cheap filesystem/input checks. |
| Status stage table | include | Lets users identify failed, pending, and completed stages quickly. | Include failure summaries, log path hints, and artifact counts. |
| Artifact provenance display | include | Keeps artifact inspection useful without loading payloads. | Show generic metadata and provenance available from store APIs. |
| Live log following | defer | Useful later, but not necessary for v3 done criteria. | Can be revisited after subprocess and scheduler execution create stronger live-log needs. |
| Scheduler/job status in `loom status` | defer | V3 is local-only and scheduler integration belongs to later executor roadmap versions. | Revisit in SLURM operations or executor-specific status phases. |
| Artifact payload `cat` | defer | V3 diagnostics inspect metadata; payload display risks domain-specific behavior. | Revisit only as an explicit artifact command with codec and size policies. |
| Artifact checksum verification | defer | Useful but may be expensive and is not needed for v3 metadata inspection. | Revisit when checksum policy and opt-in verification UX are defined. |

## Design Decisions

| Decision | Selected approach | Alternatives rejected | Rationale | Revisit trigger |
| --- | --- | --- | --- | --- |
| Run addressing terminology | Use `RUN_URI` for v3 diagnostics and downstream plan language. | Public local path arguments and plain local path aliases. | Keeps CLI and persisted contracts consistent with v2. | Revisit only if a later CLI ergonomics pass explicitly adds path aliases without weakening the `run_uri` contract. |
| Operational scope | Local-only diagnostics. | Executor-specific, remote, container, scheduler, and catalog diagnostics. | Matches v3 roadmap and keeps tests environment-independent. | Revisit in v4+ or executor-specific roadmap versions. |
| Artifact inspection depth | Metadata and provenance only. | Artifact payload display and checksum verification. | Keeps v3 domain-neutral, cheap, and safe by default. | Revisit with explicit codec, payload-size, and verification policy. |
| Status command scope | Persisted local run state only. | Scheduler or live job queries. | Keeps `loom status` usable without external systems and aligned with local v3 scope. | Revisit when executor-specific status APIs land. |
| Existing CLI envelope reuse | Reuse v2 `--format text|json` and JSON envelope conventions. | A separate `--json` flag for v3 commands. | Keeps command output consistent across validate, plan, run, and diagnostics. | Revisit only if a compatibility requirement demands legacy-style `--json`. |
| Inspection API ownership | Add reusable preflight and inspection logic in separable runtime/store-owned modules, not in `loom.cli`. | CLI walking private run-store paths or assembling business records directly. | Existing protocols already expose status, stage logs, failures, artifact index, and events; CLI should format public results. Decoupling keeps Python APIs usable without shelling out. | Revisit only if a lower-layer API would create circular ownership. |
| Preflight persistence | Do not persist standalone preflight reports by default in v3. | Writing a first-class preflight report into run-store state. | Preflight is best-effort, can become stale immediately, and may run before a run exists. Users can save JSON output externally when they need an audit artifact. | Revisit if later policy or audit requirements need durable preflight report records. |
| Diagnostics package boundary | Add a reusable `loom.diagnostics` package between runtime/store APIs and `loom.cli`. | Putting diagnostics in `loom.cli`; putting preflight in pipeline internals; adding broad store-only aggregation APIs. | This is a middle ground that keeps CLI thin without forcing config composition into pipeline or store modules. | Revisit if implementation discovers narrower owner-specific facades are enough and `loom.diagnostics` would be only a pass-through. |
| Preflight run URI option | `loom preflight CONFIG` accepts optional `--run-uri RUN_URI`. | Requiring a run URI for every preflight; omitting run-specific checks entirely. | Without a run URI, users can check config, graph, selectors, executor, and default local run-root readiness; with one, they can check a specific `RUN_URI` and resolved local path safety. | Revisit if v4 runtime option models change the preflight request shape. |
| Preflight check grouping | Use repeatable `--check GROUP` with `config`, `pipeline`, `selectors`, `run`, `artifacts`, `codecs`, `executor`, and `filesystem`; default to all local groups. | Many one-off boolean flags for each check group. | Repeatable groups scale to later diagnostics while keeping v3 local-only. | Revisit if groups become too coarse for user debugging. |

## Practical Design Notes

Public Python API surface:

- Existing useful surfaces:
  - `LocalRunStore.resolve_run_uri`, `open_run`, `read_run_status`,
    `read_stage_status`, `read_stage_failure`, `read_stage_outputs`,
    `read_stage_log`, `local_stage_log_path`, `read_artifact_index`,
    `read_events`, and related protocol methods.
  - `resolve_local_run_uri`, `run_uri_to_path`, and `validate_run_uri` already
    enforce strict local `file://` `RUN_URI` syntax.
  - CLI JSON helpers already use `--format text|json` envelopes with top-level
    warnings.
- Default design direction:
  - Add preflight result models and a check runner in a runtime-owned package
    that can be reused by both `loom preflight` and `loom run`.
  - Add narrow inspection result models/facades where needed outside
    `loom.cli`, so CLI modules format `StatusSummary`, `LogSummary`, and
    `ArtifactSummary`-style objects rather than walking private files.

CLI surface:

- Default:
  - `loom preflight CONFIG`
  - `loom status RUN_URI`
  - `loom logs RUN_URI STAGE`
  - `loom artifacts list RUN_URI`
  - `loom artifacts show RUN_URI ARTIFACT_ID`
- Reuse `--format text|json` instead of adding a separate `--json` option.
- `loom preflight CONFIG` accepts optional `--run-uri RUN_URI`.
- `loom preflight` accepts repeatable `--check GROUP`; default is all local
  groups: `config`, `pipeline`, `selectors`, `run`, `artifacts`, `codecs`,
  `executor`, and `filesystem`.
- `loom logs` should expose path display and bounded content display, with
  exact option names to be confirmed.

Persisted records and file layout:

- Default: v3 should inspect existing v0-v2 run-store, log, and artifact
  records through public APIs. New persisted data should be limited unless a
  preflight report artifact or run event is explicitly chosen later.
- Default: do not persist standalone preflight report files in v3. The explicit
  `loom preflight` command reports current best-effort diagnostics, and
  `loom run` reuses a minimal preflight subset before execution.

Import boundaries and dependencies:

- CLI code should remain an outer layer and avoid imports from lower-level
  packages into `loom.cli`.
- Preflight reusable logic should not live only in CLI modules if `loom run`
  must call it.
- `loom.diagnostics` should depend on public config, pipeline, planning,
  execution, store, artifact, codec, and URI APIs. Those lower layers should not
  import `loom.diagnostics`.
- No new heavyweight runtime dependencies by default.

Failure modes and diagnostics:

- Stable check IDs, severities, statuses, compact human output, and JSON output
  are central to the design.
- Missing logs, missing artifact IDs, unreadable run URIs, unsafe resolved local
  run-store state, and graph/config failures should produce structured errors.
- Preflight results should distinguish `PASS`, `WARN`, `FAIL`, and `SKIP`.
- `--strict` should treat warnings as command failure for explicit preflight.

Maintainability and extensibility:

- Preflight check groups should allow later executor-specific checks without
  hard dependencies on those executors in v3.
- Status/log/artifact commands should use store API facades so future run-store
  layout changes do not require CLI path rewrites.

Scalability and future compatibility:

- Avoid expensive checksum scans or payload reads by default.
- Keep output schemas simple enough to evolve for catalogs, remote stores, and
  executor-specific status later.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Preflight remains best-effort and local-only in v3. | Roadmap defers runtime profiles and external executor checks. | Revisit when v4+ runtime/resource/executor surfaces land. |

## Phase Sketch

### Phase 1 - Diagnostics Foundation And Preflight Core

Goal:

- Introduce the reusable diagnostics layer and local preflight result/check
  model without adding user-facing diagnostic commands yet.

Scope:

- Add `loom.diagnostics` package boundaries and public exports.
- Add preflight statuses, severities, check result models, overall result
  model, check IDs, group selection, and non-persistent preflight request API.
- Implement the local check runner and local check groups for config, pipeline,
  selectors, `RUN_URI`, local artifact store, codec registry, local executor,
  and cheap filesystem/input checks as public Python APIs.
- Keep the runner reusable by both `loom preflight` and `loom run`.

Out of scope:

- CLI `preflight`, `status`, `logs`, or `artifacts` commands.
- Persisted preflight reports.
- External executor, scheduler, plugin, remote, or container checks.

Acceptance criteria:

- Public Python APIs can run the full local preflight set and selected check
  groups against synthetic local configs.
- Results distinguish `PASS`, `WARN`, `FAIL`, and `SKIP`, carry stable check
  IDs, and serialize to plain data.
- Check groups validate unknown names clearly.
- No preflight result is written to the run store by default.
- Functional user benefit is indirect unless downstream users call the Python
  diagnostics API directly; the phase primarily creates the tested foundation
  needed for the CLI phase.

Test expectations:

- Package: import-boundary tests for `loom.diagnostics`.
- Unit: result model validation, group selection, status aggregation, strict
  warning policy helpers if implemented in core.
- Contract: stable check ID and plain-data serialization contracts.
- Integration: config, graph, selector, `RUN_URI`, local store, codec, executor,
  and filesystem checks using synthetic fixtures.
- E2E: not required in this phase.
- Opt-in: none.

Design impact:

- Adds a new middle-layer package that depends on public config, pipeline,
  planning, store, artifact, codec, and URI APIs while remaining independent of
  `loom.cli`.

Future compatibility:

- Check groups should allow later executor-specific and remote checks without
  hard dependencies in v3.

Alternatives rejected:

- Putting reusable preflight logic in `loom.cli`.
- Putting config-aware preflight orchestration inside pipeline internals.
- Persisting preflight reports as first-class run-store documents in v3.

Debt introduced:

- Local-only best-effort checks do not cover future runtime/resource profiles
  or external backends.

Reviewability:

- Reviewable as one API/model/check-runner PR without CLI output churn. If
  every phase should provide immediate CLI-visible value, this phase should be
  combined with Phase 2.

### Phase 2 - Preflight CLI And Run Reuse

Goal:

- Expose preflight diagnostics through the CLI and reuse the minimal local
  preflight subset before `loom run` execution.

Scope:

- Add `loom preflight CONFIG` with `--format text|json`, `--strict`,
  optional `--run-uri RUN_URI`, and repeatable `--check GROUP`.
- Format compact human preflight output and stable JSON envelopes through
  existing CLI helpers.
- Reuse a minimal non-persistent preflight subset in `loom run` for config
  load, graph validation, `RUN_URI`/resolved path safety, and executor
  resolution.
- Add CLI tests for successful, warning, failing, strict, JSON, selected-group,
  and optional-run-URI behavior.

Out of scope:

- `status`, `logs`, or `artifacts` commands.
- Persisted preflight reports.
- External executor checks and policy files.

Acceptance criteria:

- Users can run explicit local preflight before execution.
- `--strict` fails when warnings are present.
- `--check` limits the run to selected local groups and rejects unknown groups.
- `loom run` reuses the minimal subset without duplicating preflight logic in
  CLI code.

Test expectations:

- Package: CLI import-light checks remain passing.
- Unit: parser/options, text formatting, JSON payload shape, strict exit-code
  mapping.
- Contract: CLI result envelope compatibility with v2 conventions.
- Integration: preflight command against synthetic valid and invalid configs.
- E2E: one successful local preflight and one failing local preflight through
  `main(argv)`.
- Opt-in: none.

Design impact:

- Extends the v2 CLI command surface while preserving `--format text|json` and
  the thin-CLI rule.

Future compatibility:

- The check group interface can grow with v4+ runtime options and later
  executor families.

Alternatives rejected:

- Adding a one-off `--json` flag for preflight.
- Recomputing preflight checks directly inside `loom.cli.run`.

Debt introduced:

- Minimal `loom run` preflight remains a safety screen, not a durable audit log
  or substitute for runtime validation.

Reviewability:

- Reviewable as one CLI integration PR with narrow behavior and command tests.

### Phase 3 - Status And Logs Inspection

Goal:

- Let users inspect run status and stage logs through CLI commands backed by
  reusable diagnostics inspection facades.

Scope:

- Add diagnostics result models/facades for persisted run status, stage status
  table, failure summaries, artifact counts, and log path hints.
- Add diagnostics result models/facades for stage log path lookup and bounded
  content display.
- Add `loom status RUN_URI` with text and JSON output.
- Add `loom logs RUN_URI STAGE` with resolved path display and bounded content
  display; exact option names are finalized in the implementation plan.
- Add tests for successful runs, failed runs, missing runs, missing stages,
  missing logs, and corrupt store documents where practical.

Out of scope:

- Scheduler or job status.
- Live log following and unbounded tailing.
- Artifact list/show commands.

Acceptance criteria:

- A successful local run and a failed local run can be summarized without
  importing project stage modules.
- Failed stage summaries include useful failure and log path hints.
- Logs can display paths and bounded content through public store APIs.
- JSON output uses stable CLI envelopes.

Test expectations:

- Package: import boundaries prevent lower layers from importing CLI or
  diagnostics incorrectly.
- Unit: status/log summary models and formatting.
- Contract: diagnostics facade reads through store protocols rather than private
  paths where public methods exist.
- Integration: local run-store fixtures for success, failure, and missing log
  cases.
- E2E: `loom status` and `loom logs` over synthetic successful and failed local
  runs.
- Opt-in: none.

Design impact:

- Adds reusable inspection APIs that CLI and future tools can call without
  shelling out.

Future compatibility:

- Status summaries should leave room for later catalog, remote store, and
  executor-specific status fields without querying those systems in v3.

Alternatives rejected:

- Direct CLI traversal of local run-store file paths.
- Scheduler/job queries in the general status command.

Debt introduced:

- Bounded log display is intentionally simpler than tail/follow behavior.

Reviewability:

- Reviewable as one post-run inspection PR focused on run state and logs.

### Phase 4 - Artifact Inspection And End-To-End Diagnostics

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

Out of scope:

- Artifact payload `cat`.
- Artifact checksum verification.
- Run catalog, comparison, export/import, retention, or cleanup.

Acceptance criteria:

- Users can list recorded artifacts and inspect one artifact's metadata without
  loading payloads.
- Missing artifact IDs fail clearly.
- Successful and failed local runs can be diagnosed end to end through CLI text
  output.
- JSON output remains stable for automation-facing diagnostics.

Test expectations:

- Package: public artifact diagnostics imports are stable.
- Unit: artifact summary models and formatting.
- Contract: artifact diagnostics read `ArtifactRef` metadata through public
  run-store APIs.
- Integration: artifact list/show over local run-store fixtures.
- E2E: full local workflow using `preflight`, `run`, `status`, `logs`, and
  `artifacts`.
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

Debt introduced:

- Artifact inspection is metadata/provenance-only until a later command defines
  payload and checksum policies.

Reviewability:

- Reviewable as one artifact-focused PR plus end-to-end diagnostic evidence.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Should v3 optimize first for new/local CLI users debugging runs, or for automation that consumes stable JSON diagnostics? | Output design, phase order, and test emphasis. | Local CLI debugging first, with stable JSON for automation where commands already expose it. | answered |
| Should v3 expose diagnostics only as `RUN_URI`, or should it accept plain local paths as ergonomic aliases while preserving `run_uri` internally? | CLI compatibility and user ergonomics. | Require `RUN_URI`, matching v2. | answered |
| Is the v3 plan expected to include all four command families: preflight, status, logs, and artifacts? | Scope size and phase breakdown. | Include all four because the roadmap lists them as the v3 user-visible outcome. | answered |
| Should `loom logs` include live follow or tail semantics in v3? | CLI scope and testing. | Show resolved log paths and bounded content display; defer live follow and unbounded tailing. | answered |
| Should preflight include the full local check set from the roadmap? | Preflight API and phase scope. | Include config, graph, selectors, `RUN_URI` safety, local artifact store, codec registry, local executor, and cheap filesystem/input checks. | answered |
| Should `loom status` include scheduler or job status? | Status scope and external dependencies. | No; show persisted run state, stage table, failures, log hints, and artifact counts only. | answered |
| Should artifact commands read payloads or verify checksums? | Artifact command scope and performance. | No; list/show metadata and provenance only in v3. | answered |
| Should v3 diagnostics reuse `--format text|json` or add a separate `--json` flag? | CLI consistency and roadmap wording. | Reuse `--format text|json`; treat roadmap `--json` as fulfilled by `--format json`. | answered |
| Should v3 persist explicit preflight reports? | Persisted schema and run layout. | No; report current diagnostics and keep `loom run` minimal preflight non-persistent. | answered |
| Where should reusable preflight and inspection logic live? | Import boundaries and maintainability. | Runtime/store-owned modules outside `loom.cli`; CLI only parses, calls, formats. | answered |
| Should v3 add a reusable diagnostics package? | Source-tree boundary and API ownership. | Add `loom.diagnostics` as a middle layer between runtime APIs and CLI. | answered |
| Should explicit preflight require a run URI? | Preflight ergonomics and run-specific checks. | Optional `--run-uri`; no URI checks general readiness, URI checks specific path safety. | answered |
| How should preflight check groups be selected? | CLI ergonomics and future extensibility. | Repeatable `--check GROUP` with local v3 groups; default all local groups. | answered |
| Should the diagnostics foundation be a separate phase despite low direct CLI-visible benefit? | Phase granularity and reviewability. | Keep separate for reviewability, with the implementation-plan draft allowed to combine it with Phase 2 if it judges the user-visible value tradeoff differently. | answered |
| What functional benefit does v3 provide as a roadmap section? | Roadmap framing and user-visible value. | V3 is the local observability/debugging layer after v2: preflight before running, status/log/artifact inspection after running, without manual run-store file inspection. | answered |

## Handoff Notes

Implementation-plan draft inputs:

- V3 functional framing: local observability and debugging over the v2 local run
  capability.
- Primary outcome: users can preflight a config, run locally, inspect status,
  view stage logs, and inspect recorded artifact metadata without knowing the
  run-store file layout.
- Target audience: local terminal users debugging or validating single-run
  `loom` pipelines.
- Public run argument: `RUN_URI`; avoid public local-path argument language in
  v3 plan artifacts.
- CLI output: reuse `--format text|json` and v2 JSON envelope conventions.
- Preflight:
  - Add reusable models and runner under `loom.diagnostics`.
  - Include config, pipeline graph, selector, `RUN_URI`, local artifact store,
    codec registry, local executor, and cheap filesystem/input checks.
  - Use optional `--run-uri RUN_URI`.
  - Use repeatable `--check GROUP` for `config`, `pipeline`, `selectors`,
    `run`, `artifacts`, `codecs`, `executor`, and `filesystem`; default all
    local groups.
  - Add `--strict`.
  - Keep preflight non-persistent by default.
  - Reuse a minimal non-persistent subset from `loom run`.
- Status:
  - `loom status RUN_URI` reads persisted local run state only.
  - Show run status, stage table, failure summaries, log path hints, and
    artifact counts.
  - Defer scheduler/job status.
- Logs:
  - `loom logs RUN_URI STAGE` shows resolved log paths and bounded content.
  - Defer live follow and unbounded tailing.
- Artifacts:
  - `loom artifacts list RUN_URI` and `loom artifacts show RUN_URI ARTIFACT_ID`
    are metadata/provenance-only over public run-store APIs.
  - Defer payload `cat` and checksum verification.
- Phase sketch:
  - Phase 1: diagnostics foundation and preflight core.
  - Phase 2: preflight CLI and run reuse.
  - Phase 3: status and logs inspection.
  - Phase 4: artifact inspection and end-to-end diagnostics.

Plan-quality-gate risks:

- Downstream v3 artifacts must consistently use `RUN_URI` for public
  diagnostics.
- Preflight logic must be reusable by `loom run` without putting business logic
  in CLI modules.
- The artifact/log/status inspection surface must avoid hard-coding private
  local run-store paths where public APIs should own layout knowledge.

Assumptions to carry forward:

- V3 diagnostics use `RUN_URI` as the public run argument.
- V3 prioritizes local terminal debugging for single-run pipelines while
  preserving stable JSON output where exposed.
- V3 is framed as local observability and debugging over the v2 run capability,
  not as a new execution capability.
- V3 includes all four local diagnostics command families.
- V3 log inspection starts with resolved paths and bounded content display.
- V3 preflight includes the full local check set but no external executor,
  plugin, container, remote, or scheduler checks.
- V3 status reads persisted local run state only.
- V3 artifact commands are metadata/provenance-only.
- V3 adds `loom.diagnostics` as the reusable preflight and inspection layer
  above public runtime/store APIs and below `loom.cli`.
- V3 preflight is non-persistent by default.
