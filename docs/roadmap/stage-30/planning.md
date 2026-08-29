# Roadmap Stage 30 Planning: Capability Journeys And Guide Clarity

Status: approved
Roadmap stage: 30
Evidence tree: `/home/can134/work/active/loom-worktrees/stage-30-p1-operations-portability-and-cleanup` at `e3968f7`; relevant dirty paths: none in the evidence worktree. The control checkout has unrelated Stage 29 planning edits and is excluded from this stage.
Planning route: lean
Current gate: approval complete
Blockers: none

This file is current authoritative state. Stage 30 is a documentation,
examples, and validation stage over behavior that is already implemented. It
does not add Loom runtime functionality.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Public commands and Python APIs exist for the requested journeys, with unit, contract, integration, or e2e coverage but incomplete user-facing examples. | None. | Use the existing surfaces exactly as implemented. |
| Functionality | Add seven focused, domain-neutral journeys and strengthen the existing local resume journey. | None. | Implement in three vertical phases. |
| Design | Examples remain deterministic, local/fake-backed, network-free, and honest about setup and external prerequisites. | None. | Reuse the Stage 22 manifest and example harness. |
| Validation | Every runnable claim gets a named integration/e2e path, with actual entrypoints executed. | None. | Add focused example tests and retain repository gates. |
| Detailed plan | Compact manifest and three linked phase plans use `manifest-and-phase-plans-v1`. | None. | Start Phase 1. |
| Approval | The maintainer explicitly requested implementation of the attached examples-and-guides brief on 2026-08-21. | None. | Execute the approved manifest. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `docs/roadmap.md` and completed Stage 22 | Stage 22 established the example manifest contract, public-surface-first rule, and local/fake validation model. Its operations catalog explicitly reserved run catalogs, bundles, cleanup, and GC for later examples. | Stage boundary and validation model | FR-1, FR-2, FR-8 |
| `src/loom/cli/runs.py` and `tests/e2e/test_cli_runs_e2e.py` | Index, list, diff, export, inspect, and import already work and emit stable JSON envelopes. | Run portability journey | FR-1 |
| `src/loom/cli/clean.py`, `src/loom/cli/gc.py`, and `tests/e2e/test_cleanup_cli.py` | Cleanup previews by default and deletes only after `--delete --yes`; collection GC preserves run directories. Cleanup authority comes from recorded candidates, not filesystem scanning. | Safe deletion journey | FR-2 |
| `src/loom/cli/sweep.py` and `tests/e2e/test_sweep_cli.py` | Manual deterministic sweep plan/run/status/collect already exist. | Experiment journey | FR-3 |
| `src/loom/pipeline/event_sinks.py` and local execution integration tests | An instance-local `EventSinkRegistry` observes committed lifecycle facts and isolates callback failures from pipeline success. | Extension journey | FR-4 |
| Apptainer executor, preflight, SLURM composition, and fake-runner tests | Apptainer and Singularity execution are implemented without a user-facing copyable project. | HPC container journey | FR-5 |
| `examples/execution/local/` and resume tests | The current example proves same-run reuse, but does not summarize fingerprints or a changed-input downstream rerun. | Resume clarity | FR-6 |
| Artifact backend contracts and `materialize_artifact_locally` tests | Registry/capability records, fake payload handlers, and explicit checksum-verified local copy materialization exist; no first-party remote provider is selected. | Storage journey | FR-7 |
| Feature docs for run catalogs, reliability, sweeps, containers, resume, remote stores, and plugins | Current and deferred behavior is often separated only deep in long design/specification prose. | Guide clarity | FR-8 |

- User-visible outcome: a user can copy and run small examples for Loom's
  multi-run, maintenance, sweep, observer, HPC-container, resume, and artifact
  materialization capabilities without reading tests or adopting an external
  service.
- Existing end-to-end path: each capability already has a public CLI or Python
  entrypoint and lower-level validation; Stage 30 connects those surfaces into
  complete journeys.
- Included scope: example directories, example catalog routing, focused
  integration/e2e validation, the existing local example, and compact current
  support/quick start/deferred summaries in the feature documents directly
  owned by these journeys.
- Non-goals and deferrals: no runtime APIs, schemas, plugins, providers,
  notification adapters, tracking server, cloud SDK, network access, real
  scheduler/container requirement, arbitrary cleanup authority, or broad docs
  generation system.
- Current consumers, boundaries, or demonstrated failures: users currently
  have to reconstruct these workflows from feature specifications and tests;
  cleanup has a destructive safety boundary; event sinks have a failure
  isolation boundary; Apptainer has an external-runtime boundary; external
  artifacts have a deliberate no-provider boundary.
- Public or durable surfaces affected: none. Examples consume existing public
  surfaces. Example manifests and documentation links are repository-owned
  validation metadata, not runtime contracts.

## Minimum Useful Change

- Smallest useful behavior: focused example entrypoints that execute the actual
  supported command/API path, assert the important result, and print a small
  stable summary.
- Closest existing capability and reuse decision: extend the Stage 22 example
  inventory, `examples.support`, and existing example integration/e2e harness;
  mirror the fake Docker approach for Apptainer.
- Why a new surface is required: no new runtime surface is required. New
  example directories are needed because combining all capabilities into one
  project would hide their safety and ownership boundaries.
- Explicitly deferred behavior: service-specific notifications, event filters,
  real remote artifact providers, credential behavior, live HPC validation,
  whole-run deletion, automatic cleanup-candidate invention, sweep metric
  interpretation, and hosted documentation.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Add `operations.run-catalog-and-bundles`: create two real completed runs, index/list/diff them, export/inspect/import one bundle with payloads, and prove imported payload equality. | No tracking server or new bundle behavior. | Existing runs CLI and local stores. | Run the entrypoint and assert count, differences, archive, imported run, and payload bytes. | locked |
| FR-2 | Add `operations.cleanup-and-gc`: preview and explicitly delete registered candidates, prove preview is inert, prove committed artifacts and run directories remain, and demonstrate collection GC. | No arbitrary path deletion or whole-run deletion. A setup-only fixture may create known authority candidates because candidate creation is not a public authoring API. | Existing cleanup CLI and authority facts. | Run the entrypoint and assert selected/deleted counts and filesystem preservation. | locked |
| FR-3 | Add `experiments.deterministic-sweep`: plan, run, status, and collect exactly two ordinary trials. | No metric interpretation, optimizer, parallel scheduler, or provider. | Existing sweep CLI. | Assert two plans, two succeeded trials, and two collected artifact refs. | locked |
| FR-4 | Add `extensions.event-sink`: directly register successful and failing observers, observe committed event names, and prove failure isolation/evidence. Include plugin entry-point packaging as secondary guidance only. | No filters, retries, message templates, or service adapter. | Existing event sink registry and runner request. | Assert run success, lifecycle event coverage, and one recorded observer failure. | locked |
| FR-5 | Add `execution.containers.slurm-apptainer`: run the public Apptainer executor with a fake command, prove `exec --cleanenv --nv` construction, and document optional live preflight/run commands plus SLURM composition. | No real container or scheduler in default validation. | Existing Apptainer executor and Docker example pattern. | Execute fake CLI journey and assert command log and successful artifacts. | locked |
| FR-6 | Strengthen `execution.local`: print config/pipeline fingerprint evidence, assert unchanged reuse, and show a changed input causing only the affected branch to rerun. | No resume-policy change. | Existing runner/planner behavior. | Example test asserts first actions, reuse actions, changed-input actions, and fingerprints. | locked |
| FR-7 | Add a storage example for an explicit fake artifact backend and checksum-verified local materialization. | No first-party cloud provider or hidden download. | Existing backend registry/payload contracts and local materialization API. | Assert registered backend kind, explicit operation result, copied bytes, checksum evidence, and unsupported provider boundary. | locked |
| FR-8 | Route every new example from group/root catalogs, maintain valid manifests, and add compact `Current Support`, `Quick Start`, and `Deferred` sections to the directly related major feature docs. | No repository-wide prose rewrite or generated docs system. | Stage 22 inventory checks. | Manifest/catalog tests, link checks, and review of current/deferred claims. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1..FR-8 | Treat the request as examples/docs completion rather than runtime expansion. | All requested capabilities have existing public entrypoints and tests. | Examples must expose existing limitations instead of smoothing them over. | locked |
| FQ-2 | FR-2 | Use a setup-only authority fixture for known cleanup candidates. | Deletion commands are public, while candidate invention is intentionally not a general public surface. | The setup code is not production guidance; README commands remain the supported user path once Loom has recorded candidates. | locked |
| FQ-3 | FR-5, FR-7 | Use fake adapters by default and document live/provider prerequisites separately. | Matches existing Docker and Stage 22 validation policy. | Fake validation proves Loom integration and command/protocol shape, not a real external system. | locked |

## Behavior Baseline

- Included and default behavior: every runnable script chooses a temporary or
  environment-directed output root, is rerunnable, avoids network access, uses
  synthetic data, and prints deterministic key/value evidence.
- Failure and unsupported behavior: observer exceptions become observer-failure
  facts without changing run success; cleanup cannot delete unregistered or
  unsafe paths; non-local/provider payload work remains explicit and
  unsupported; live Apptainer/SLURM remains optional.
- Reproducibility and durable behavior: examples use normal run URIs,
  fingerprints, catalog indexes, bundle manifests, sweep manifests, artifact
  refs/checksums, and authority cleanup facts. They do not create alternate
  formats.
- Explicit deferrals: provider adapters, notifications, arbitrary metrics,
  deletion policy expansion, real HPC in CI, and new runtime machinery.

## Minimum Design

- Modules and ownership: `examples/` owns user projects and group routing;
  `tests/integration/examples` and representative e2e tests own runnable
  evidence; feature docs own current/deferred explanation. `src/loom` is not
  changed.
- Data and control flow: example setup creates ordinary authored config and
  local inputs, public Loom entrypoints produce normal records, the script reads
  only public result shapes or persisted user-facing output, and tests assert a
  compact summary plus important files.
- Fixed public, durable, trust-boundary, and cross-phase contracts: existing CLI
  JSON envelopes, public Python objects, example manifest fields, explicit
  cleanup intent, observer isolation, checksum verification, and fake/live
  boundary remain unchanged.
- Private implementation discretion: helper names, summary formatting, fake
  executable internals, test factoring, and exact synthetic payloads may be
  simplified while keeping acceptance evidence.
- Extension and compatibility seams: event-sink packaging and artifact backend
  handlers are shown as caller-supplied extensions; no import-time global
  registration is added.
- Import and dependency direction: examples may import Loom and project-local
  stage/helper code; Loom never imports examples. No new runtime dependency.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Seven focused example directories plus one existing-example update | Current user journeys are missing. | One mega-example would couple unrelated prerequisites and safety models. | keep |
| Setup-only cleanup fixture | Required to demonstrate existing deletion behavior without a new public candidate-authoring API. | Invent a runtime API or scan paths. | keep, label clearly |
| Fake Apptainer executable | Required for hermetic public CLI execution. | Documentation-only commands would not prove the journey. | keep |
| Fake artifact backend | Required to show registry/capability flow without a provider SDK. | Claim a cloud provider is supported. | keep |
| Current/quick/deferred summaries in directly related docs | Needed to separate implemented behavior from design history. | Rewrite all feature docs. | keep bounded scope |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1..FR-8 | Keep all runtime files out of scope. | The requested stage is demonstrability work over existing behavior. | A discovered runtime gap becomes an honest documented limit, not scope growth. | locked |
| DQ-2 | FR-1..FR-7 | Validate actual entrypoint behavior, not snippets alone. | Stage 22's quality bar requires runnable public journeys. | Full examples add some test time; keep them focused and use targeted suites. | locked |
| DQ-3 | FR-8 | Apply the three-section pattern only to docs owned by these examples. | This provides immediate clarity without a broad speculative rewrite. | Other feature docs can adopt the pattern when touched. | locked |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Run catalog and bundle | Multi-run identity, comparison, and portable payload equality | Runs CLI and bundle formats | One full integration journey | planned |
| Cleanup and GC | Preview inertness and candidate-only deletion | Authority candidates plus cleanup CLI | One full integration journey including per-run and collection behavior | planned |
| Deterministic sweep | Two normal runs and metadata/ref collection | Sweep CLI/manifests | One full integration/e2e journey | planned |
| Event sink | Committed facts and callback isolation | Runner event dispatcher/authority failure facts | One Python API integration journey | planned |
| Apptainer | Correct fake command and truthful live boundary | Public executor and command builder | One fake-command e2e journey | planned |
| Resume | Fingerprint-backed reuse and branch invalidation | Planner actions and persisted artifacts | Existing smoke plus focused integration assertions | planned |
| Artifact materialization | Explicit copy/checksum evidence and no-provider boundary | Public backend/materialization contracts | One Python API integration journey | planned |
| Docs/catalog truth | No orphaned manifest, link, or overclaim | Stage 22 inventory harness and feature docs | Existing inventory checks plus focused assertions if needed | planned |

Causal interactions requiring combined coverage:

- Run catalog, diff, export, inspect, import, and payload verification must be one
  journey because the user value is their handoff sequence.
- Cleanup preview and delete must operate on the same candidate, and collection
  GC must prove run-directory preservation.
- Event sink success and failure callbacks must share one successful run to
  prove isolation.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Operations portability and cleanup | Users can compare/transfer runs and safely preview/delete cleanup candidates. | Operations examples/catalog/tests; no runtime edits. | Existing Stage 8/12/21/26 surfaces. | Both entrypoints execute and assert their complete journeys. | ready |
| 2. Experiments, observers, and HPC containers | Users can run a two-trial sweep, attach observe-only sinks, and exercise Apptainer hermetically. | Experiments/extensions/execution examples and routing; no providers or filters. | Phase 1 only for shared catalog conventions. | Three entrypoints execute with lifecycle, failure-isolation, and command assertions. | pending |
| 3. Resume, storage, and guide clarity | Users see why resume reuses/reruns work, can perform explicit materialization, and can quickly distinguish current/deferred support. | Existing local example, storage group, related feature docs; no runtime edits. | Phases 1-2 for final catalogs. | Resume/materialization journeys and docs inventory pass; full repository validation passes. | pending |

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Explicit implementation request plus FR/FQ/DQ tables | pass |
| Minimum design justified | Reuses existing example harness and public surfaces; no runtime change | pass |
| Complexity delta proportionate | Focused examples and bounded docs sections only | pass |
| Contracts and private discretion clear | Existing public/durable shapes fixed; helpers remain private | pass |
| Invariant ownership and validation proportionate | Each risky boundary has one complete journey plus existing lower-level tests | pass |
| Phases vertical and reviewable | Three user-goal phases with separate ownership | pass |
| No unresolved blocker | Cleanup setup limitation has an explicit truthful fixture decision | pass |

Gate result: passed; ready for implementation.
Accepted risks and revisit triggers: fake adapter examples do not prove real
external systems; revisit only when Loom selects a concrete optional provider or
the default suite gains a deterministic live fixture. The cleanup setup fixture
is not a public candidate-authoring recommendation; revisit if Loom later adds a
supported producer-facing candidate API.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Runtime code | No changes. | Capability already exists; the user asked for examples/guides. | A required journey cannot be executed through current public behavior. |
| Cleanup setup | Isolate private fact seeding from demonstrated CLI behavior and explain the boundary. | Avoids arbitrary deletion authority. | Public candidate producer is introduced. |
| Plugin packaging | Secondary event-sink README section only. | Direct registry is the simplest supported path. | A real distributable example package is needed. |
| External providers | Fake backend plus local explicit materialization only. | No first-party provider is selected. | Concrete adapter requirement is accepted. |
| Live Apptainer/SLURM | Manual commands only. | Default validation must remain hermetic. | Deterministic live infrastructure exists. |
| Broad docs rewrite | Deferred. | Only directly related major docs need immediate current/quick/deferred clarity. | Another feature doc is materially confusing when next changed. |
