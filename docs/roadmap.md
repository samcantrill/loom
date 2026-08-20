# Implementation Roadmap

## Purpose

This document is the staged implementation roadmap for `loom` after the
feature specifications in `docs/features/`.

It is still a roadmap, not a detailed project plan. Each version below should
later become a dedicated implementation plan with concrete interfaces, phase
boundaries, test strategy, compatibility notes, review gates, branch/worktree
metadata, and accepted technical debt.

The canonical v0 plan remains
[`docs/roadmap/stage-0/implementation-plan.md`](roadmap/stage-0/implementation-plan.md).
v0 is intentionally larger than a normal roadmap step because it is already
split into detailed internal phases. After v0, each roadmap step should be
small enough to become one comprehensive project plan without needing to
combine unrelated subsystems.

## Roadmap Refinement Summary

The first roadmap grouped the planned work into v0 through v9. That was useful
for module coverage, but several steps were too broad to become consistent
project-plan units. This revision keeps the same implementation direction but
splits oversized steps:

- The original local-operations step is split into CLI core and local
  diagnostics/preflight.
- Recursive config-file composition is added as its own post-v0 step before CLI
  exposure so command-line workflows can rely on the richer config surface.
- Runtime options are separated from stage-worker and subprocess execution.
- SLURM is split into script planning/dry-run and live submission/operations.
- Many-run workflows are split into run catalog, queued run dispatch, bundle
  export/import, and deterministic sweeps.
- A persistence and concurrency foundation is inserted after the run catalog so
  concurrent DAG execution, large sweeps, shared filesystems, and remote-capable
  stores do not inherit single-writer local-run assumptions.
- A post-v9 authority-unification step is inserted before bundles and sweeps so
  all mutating entrypoints use authoritative lifecycle state and stronger
  service/database backends can satisfy multi-host guarantees without preserving
  local-file runtime escape hatches.
- A DB-backed authority service supervisor step is inserted as v10 because
  v9-post intentionally stops at an in-memory co-located service. Production-like
  execution needs a durable service lifecycle, strict connect-or-fail behavior,
  explicit offline-first import, and service-backed workspace coordination
  before bundles, sweeps, remote stores, containers, and reliability features
  build on runtime authority.
- A queued run dispatch and resource-pool step is inserted as v11 because users
  need to submit many whole-run jobs without mandatory Kubernetes, Docker,
  brokers, cloud services, or other external orchestrators. This step consumes
  v10 authority and resource-lease primitives while keeping scheduling policy
  outside authority truth.
- External and remote artifacts are split into backend-neutral interface/API,
  multi-location ref semantics, and explicit immutable artifact reuse first,
  then explicit payload materialization and optional backend adapter work only
  if selected by a concrete need.
- Container execution is split into Docker and Apptainer/SLURM composition.
- Reliability is split into retry/timeout/transaction policy, runtime
  events/event sinks, and cleanup/retention/GC.
- An examples and validation refinement step is appended after
  cleanup/retention so the implemented surface can be demonstrated through
  robust runnable examples, integration tests, end-to-end tests, and updated
  documentation.
- An operational lifecycle and recovery validation step is inserted after the
  Stage 23 managed-local follow-up so real signals, child termination, timeout,
  unclean loss, authority loss, artifact corruption, and resume are proven
  before later queue-policy and downstream-operations work.
- Trusted config authoring is supplied by the external `weave` dependency;
  Loom roadmap stages should focus on runtime adapters, execution, stores,
  artifacts, and operations rather than owning config-package implementation.

The result is a longer roadmap, but each version has a more comparable scope
and a clearer acceptance boundary.

## Roadmap Quality Bar

Every post-v0 version should satisfy these expectations before implementation
starts:

- One primary user-visible outcome.
- One main package cluster or adapter family.
- Explicit prerequisites from earlier roadmap steps.
- Clear public API surface and CLI surface, if any.
- Persisted file/schema changes called out explicitly.
- Optional dependencies isolated behind adapters or plugins.
- Tests that can run without real clusters, containers, cloud services, or
  network access by default.
- A short list of deferred work that prevents scope creep.
- Reviewability as one project plan and one implementation sequence.

If a version needs two unrelated public APIs, two external systems, or multiple
new persisted schemas, it should be split before the detailed project plan is
written.

## Planning Principles

- Keep `loom` domain-neutral. Project code owns concrete stages, codecs,
  datasets, models, metrics, reports, recipes, and domain schemas.
- Preserve the source-tree and import boundaries in
  [`docs/structure.md`](../structure.md).
- Treat v0 as the local, inspectable runtime kernel: config composition,
  primitives, local I/O, static pipeline DAGs, local stores, conservative
  same-run-directory resume, and local in-process execution.
- Add operational layers only after the Python APIs and persisted run layout
  they expose are stable.
- Prefer generic contracts plus optional adapters over hard dependencies on
  cloud, cluster, container, dashboard, or domain frameworks.
- Treat external systems such as Hydra, MLflow, Prefect, DVC, W&B,
  OpenTelemetry, and cloud stores as optional integration adapters around
  `loom` contracts. `loom` remains the source of truth for pipeline semantics,
  run directories, artifact references, fingerprints, resume decisions, and
  provenance.
- Treat the post-v9 authoritative persistence backend as the source of truth
  for active run state. Human-readable local files may remain useful for
  payloads, logs, config/provenance materialization, or later export workflows,
  but active state readers should use backend-neutral store contracts and
  capabilities rather than legacy local-file state.
- Treat direct `LocalRunStore` runtime mutation as deprecated after v9. Local
  store helpers may remain internal materialization and read-compatibility
  tools, but new run, stage, worker, submitted-job, and continuation mutations
  should enter through authority-backed store factories.
- Treat implicit in-process service startup as a development convenience, not a
  production authority policy. After v10, runtime entrypoints should connect to
  an explicitly configured or registry-discovered service and fail closed when
  one is unavailable, unless the user explicitly selects offline-first
  execution and later imports the run into authority.
- Keep every version useful on its own and reviewable as a coherent product
  increment.

## Version Overview

| Version | Theme | Primary outcome |
| --- | --- | --- |
| v0 | Local runtime kernel | Local Python API for composing, running, tracing, and resuming static artifact DAGs in one run directory. |
| v1 | Rebuildable config composition | Explicit `_include_` and `_replace_` composition for nested config files, component swaps, provenance, and artifact-safe source records; `_copy_` remains deferred. |
| v2 | CLI core | Thin `loom` CLI for validate, plan, and run over the v0 local runtime. |
| v3 | Local diagnostics and preflight | Preflight checks plus status, logs, and artifact inspection for local runs. |
| v4 | Runtime options and resources | Typed invocation, resume, execution, profile, and resource models shared by later executors. |
| v5 | Stage worker and subprocess execution | Stable one-stage worker contract, subprocess executor, logs, and baseline failure records. |
| v6 | SLURM script planning | Scheduler-neutral resource mapping, SLURM models, script builders, and dry-run manifests. |
| v7 | SLURM operations | Optional live `sbatch` submission, status, cancellation, and submission recovery. |
| v8 | Run catalog and comparison | Rebuildable local run index, run listing, filtering, and metadata comparison. |
| v9 | Persistence and concurrency foundation | Authoritative run/sweep store contracts, backend capabilities, stage attempts, leases, and commit semantics for future concurrent execution. |
| v9-post | Authority-backed runtime unification | Deprecate local-only runtime mutation, route every run/stage entrypoint through authority-backed stores, and plan the service/database authority backend for multi-host operation. |
| v10 | DB-backed service supervisor | Durable authority service lifecycle, strict online/offline policy, true offline import, and service-backed workspace coordination. |
| v11 | Queued run dispatch and resource pools | Durable whole-run queueing, one FIFO queue per pool, daemon-first control with foreground-drain compatibility, and local/SLURM launch adapters without mandatory external orchestration dependencies. |
| v12 | Run bundles, transfer, and exporters | Safe run export, transfer-interface verification, inspect, import, and compatibility exporter contracts with portable manifests. |
| v13 | Deterministic sweeps | Grid/manual sweep expansion, manifests, sequential execution, status, and collection. |
| v14 | Plugin discovery | Explicit entry point loading for ready registries plus listing/readiness records for future sources, executors, artifact stores, run exporters, event sinks, and provenance. |
| v15 | External artifact interface contract | Backend-neutral artifact-store API, external immutable refs, multi-location artifact semantics, fake handlers, bundle ref semantics, and preflight surface. |
| v16 | Artifact payload materialization | Explicit local/external/remote payload materialization, publish, upload/download paths, and at most one optional backend adapter family, if selected. |
| v17 | Docker container executor | Docker CLI executor using the stage-worker and artifact/run-store contracts. |
| v18 | HPC container execution | Apptainer/Singularity executor and SLURM-container composition. |
| v19 | Reliability policies and transactions | Retry, timeout, failure-category, status-detail, transaction, and retry-safety records across executors. |
| v20 | Runtime events and event sinks | Audit-ready runtime event grammar plus observe-only event sink contracts over committed runtime facts. |
| v21 | Cleanup and retention | Conservative cleanup, retention metadata, explicit deletion, and run-collection GC. |
| v22 | Examples and validation refinement | Robust example coverage, integration/e2e validation behavior, example harness hardening, and documentation refinement over the implemented surface. |
| v23 | Managed local concurrency and resource assignment | Pool-scoped managed-local reconcile/fill cycles, structured capacity deferral, exclusive static-slot assignment, lease-safe local process lifecycle, and redacted operational status. |
| v24 | Operational lifecycle and recovery validation | Real-process proof for interruption, cancellation, timeout, shutdown, unclean process loss, authority loss, artifact integrity, and resume without false success or orphaned ownership. |
| v25 | Resource-aware whole-run queue selection | Default-compatible FIFO selection plus a bounded queue-local policy seam for safe downstream choice of fitting managed-pool candidates. |
| v26 | Downstream operations design | Design and documentation for stage-author guidance, resource validation and usage observation, generic scheduling, notifications, resume policy, queues, and environment acceptance profiles. |

## v0 - Local Runtime Kernel

Status:

- Covered by [`docs/roadmap/stage-0/implementation-plan.md`](docs/roadmap/stage-0/implementation-plan.md).

Goal:

- Build the local reference implementation for config, primitives, pipeline
  DAGs, stores, planning, resume, provenance, and in-process execution.

Implement:

- Core primitives, timestamps, shared errors, package-wide protocols,
  serialization, fingerprints, provenance value objects, local I/O, and generic
  JSON/text/bytes codecs.
- Trusted config composition, overlays, dot-path overrides, interpolation,
  redaction, recipe expansion, and `_target_` instantiation.
- Static pipeline specs, stage specs, output specs, stage context, graph
  construction, topological ordering, input binding, and status records.
- Local artifact and run stores with inspectable JSON/YAML/text files, atomic
  writes, artifact indexes, stage inputs/outputs, fingerprints, failures, logs,
  and config/provenance snapshots.
- Deterministic planning, selectors, same-run-directory resume, downstream
  invalidation, and local in-process execution.
- Tests proving import boundaries, primitive behavior, store contracts, graph
  behavior, local execution, failure persistence, and conservative resume.

Exit criteria:

- All phases in the canonical v0 plan are merged or explicitly deferred with
  accepted risk.
- Local Python APIs can compose, plan, run, inspect persisted records, and
  resume a small static DAG without CLI-only behavior.
- The config APIs and run directory layout are documented enough for v1 through
  v3 to expose them.

Defer:

- Recursive config includes, functional CLI behavior, typed runtime/resource
  options, subprocess execution, SLURM, containers, sweeps, plugins, remote
  stores, run catalogs, retries, cleanup, dashboards, and domain features.

Primary feature docs:

- All v0-owned feature docs, especially `core-model.md`, `config.md`,
  `pipeline.md`, `pipeline-graph.md`, `run-store.md`, `artifacts.md`,
  `state.md`, `resume.md`, `provenance.md`, `execution.md`, and `testing.md`.

V1 should begin after the `v0-post-hardening-docs` closeout pass has landed
because that pass finalizes the migration notes, docs consistency, and hardening
coverage required before composition and CLI layers rely on these contracts.

## v1 - Rebuildable Config Composition

Goal:

- Add explicit recursive config composition so large project configs can be
  factored into nested files, whole components can be swapped for rapid
  experimentation, and runs can preserve enough authored inputs to rebuild
  composition without adopting Hydra defaults, launchers, sweepers, custom
  resolvers, `_copy_`, or an arbitrary YAML expression language.

Implement:

- `_include_` blocks inside mappings.
- `_replace_` blocks inside mappings for whole-section replacement during
  overlay, CLI, and sweep-generated override merges.
- Strict override semantics where `path=value` updates an existing path and
  `+path=value` explicitly adds a new variable or structured branch.
- Relative include resolution based on the including file and the mapping key
  path. For example, `model: {_include_: resnet50}` in
  `configs/experiment.yaml` resolves to `configs/model/resnet50.yaml`.
- Explicit URI include resolution limited to local paths and `file://` URIs in
  v1.
- Authoring-level merge of base config, overlays, and CLI override mappings
  before include expansion, while preserving source-location metadata for
  path-aware include resolution.
- Deterministic merge semantics where the included mapping loads first and
  sibling keys in the including mapping override it.
- Path-aware errors when an `_include_` swaps over existing mapping content
  without `_replace_: true`.
- Include stack tracking, cycle detection, composition provenance, source
  hashes, replacement records, and path-aware errors.
- Composition manifests and artifact-safe source records for base configs,
  overlays, and included files so run directories can preserve rebuildable
  config inputs.
- Tests for relative includes, nested includes, URI includes, sibling
  overrides, `_replace_`, strict update overrides, `+` add overrides, overlays
  containing includes, CLI component replacement, cycle errors, missing
  includes, source records, and provenance.

Exit criteria:

- Users can split a config into nested component files and swap components
  without hidden global search behavior.
- Component swaps cannot accidentally merge stale lower-precedence keys because
  `_include_` over existing mapping content requires `_replace_: true`.
- Override strings catch typos by default and require `+` for intentional
  additions.
- Artifact-safe config records are deterministic and contain enough provenance
  to identify every included file or URI, replacement, and source record.
- Composition directives compose cleanly with v0 overlays, dot-path overrides,
  interpolation, recipe expansion, redaction, and fingerprints.

Defer:

- Hydra-compatible defaults lists, config groups, launchers, sweepers, advanced
  list patching, broad registry aliases, arbitrary YAML expression languages,
  automatic target schema inference, untrusted config sandboxing, and automatic
  plugin-discovered composition extensions.
- Implicit global config search paths. V1 starts with including-file-relative
  resolution plus explicit URI resolution.
- Custom include resolvers beyond built-in local path and `file://` behavior.
- Custom OmegaConf-style interpolation resolvers. Revisit when there is a
  concrete need and a clear provenance/error model.

Primary feature docs:

- `config.md`
- `serialization.md`
- `io.md`
- `fingerprints.md`
- `provenance.md`
- `errors.md`
- `testing.md`

## v2 - CLI Core

Goal:

- Make the v0 local runtime usable from scripts and terminals through a thin
  CLI that delegates to Python APIs.

Implement:

- Functional `loom` entry point using `argparse`.
- `loom --help`, `loom --version`, top-level exception handling, and shared
  exit-code mapping.
- `loom validate CONFIG` over config composition and pipeline validation.
- `loom plan CONFIG` with config overlays, dot-path overrides, selector flags,
  resume flags, dry-run summaries, and machine-readable JSON output.
- `loom run CONFIG` for the local executor, including selected run directory,
  overlays, overrides, selectors, resume flags, and concise summary output.
- Shared CLI parsing helpers that convert arguments into public config,
  planning, and execution API objects without duplicating module logic.
- CLI tests and small end-to-end tests using synthetic local pipelines.

Exit criteria:

- A user can validate, plan, and run a v0 pipeline from the command line.
- JSON output exists for commands expected to be consumed by automation.
- CLI modules remain outer-layer code and are not imported by config, pipeline,
  stores, artifacts, provenance, or execution internals.

Defer:

- `loom status`, logs, artifact inspection, full preflight reports, subprocess
  worker commands, executor-specific commands, sweeps, catalogs, plugins,
  remote stores, containers, shell completion, rich progress UI, and dashboards.

Primary feature docs:

- `cli.md`
- `errors.md`
- `config.md`
- `pipeline.md`
- `resume.md`
- `execution.md`
- `testing.md`

## v3 - Local Diagnostics And Preflight

Goal:

- Give users reliable local diagnostics before and after execution without
  requiring them to inspect run files manually.

Implement:

- Preflight result models, check result models, statuses, severities, stable
  check IDs, and JSON output.
- Config, pipeline graph, selector, run directory, local artifact store, codec
  registry, local executor, and local filesystem checks.
- Minimal preflight subset reused by `loom run` for config load, graph
  validation, run directory safety, and executor resolution.
- `loom preflight CONFIG` with `--strict`, `--json`, and local-only check
  grouping.
- `loom status RUN_DIR` over public run-store inspection APIs.
- `loom logs RUN_DIR STAGE` over recorded stage log paths.
- `loom artifacts list RUN_DIR` and `loom artifacts show RUN_DIR ARTIFACT_ID`
  over public artifact/run-store APIs.
- Golden-output tests where useful and synthetic e2e tests for failed and
  successful local runs.

Exit criteria:

- A local run can be checked, executed, inspected, and debugged through the CLI.
- Preflight can fail or warn with stable IDs and machine-readable output.
- Inspection commands use store APIs rather than hard-coded private file paths
  when public APIs exist.

Defer:

- Runtime/resource profiles, subprocess checks, SLURM checks, plugin checks,
  remote credential checks, container checks, large checksum scans, and policy
  files.

Primary feature docs:

- `preflight.md`
- `cli.md`
- `run-store.md`
- `artifacts.md`
- `pipeline-graph.md`
- `errors.md`
- `testing.md`

## v4 - Runtime Options And Resources

Goal:

- Define the shared operational control surface used by subprocess, SLURM,
  containers, sweeps, and preflight without mixing invocation choices into
  semantic pipeline specs.

Implement:

- `RunOptions`, `ResumeOptions`, `ExecutionOptions`, `ResourceRequest`, and
  runtime profile models.
- Normalization and validation for executor names, dry-run flags, resume
  settings, selector fields, tags, notes, and scheduler-neutral resource
  requests.
- Config and CLI mapping into runtime option objects.
- Capability-aware validation for resource fields without executor-specific
  assumptions in the core resource model.
- Executor registry surface for resolving known executor names without loading
  optional backends eagerly.
- Preflight checks for runtime option consistency and unsupported executor
  capability declarations.
- Tests for normalization, validation, serialization, CLI/config mapping, and
  resource edge cases.

Exit criteria:

- Later executors can receive one normalized runtime/options object instead of
  ad hoc flags.
- Pipeline specs remain semantic and portable across executors.
- Resource fields do not affect semantic fingerprints unless an explicit
  fingerprint policy says so.

Defer:

- Stage-worker execution, subprocess process control, SLURM script generation,
  Docker/Apptainer mapping, retry policies, timeout enforcement, and parallel
  local scheduling.

Primary feature docs:

- `runtime-resources.md`
- `execution.md`
- `preflight.md`
- `cli.md`
- `pipeline.md`
- `testing.md`

## v5 - Stage Worker And Subprocess Execution

Goal:

- Add the process-isolated execution substrate that later executor adapters can
  reuse.

Implement:

- Stage execution request/result records for exactly one prepared stage
  attempt.
- `loom stage run --run-dir RUN_DIR --stage STAGE` as the stable worker
  command.
- Stage-worker APIs that read prepared run metadata, execute one stage, write
  outputs through store contracts, and persist a structured result.
- `SubprocessExecutor` using the same stage contract, run store, artifact store,
  fingerprint records, and failure files as local execution.
- Baseline `FailureRecord` shape for Python exceptions, exit codes, signals,
  log paths, attempt numbers, and timestamps.
- Log capture, traceback recording, redacted command recording, and nonzero
  exit-code mapping.
- Preflight checks for worker command availability and subprocess executor
  capability support.
- Tests with fake commands and synthetic stages; no real cluster or container
  requirements.

Exit criteria:

- The same small pipeline can run through local in-process execution and the
  subprocess executor with equivalent persisted semantics.
- A failed subprocess stage leaves enough structured state and logs to debug
  through v3 inspection commands.
- The worker command is stable enough for SLURM and containers to invoke.

Defer:

- SLURM submission, container command construction, automatic retries, timeout
  enforcement beyond basic process result metadata, and parallel local
  scheduling.

Primary feature docs:

- `execution.md`
- `reliability.md`
- `state.md`
- `run-store.md`
- `cli.md`
- `preflight.md`
- `testing.md`

## v6 - SLURM Script Planning

Goal:

- Make SLURM execution inspectable and testable before adding live scheduler
  submission.

Implement:

- SLURM option models, modes, job records, submission records, and script
  builder interfaces.
- Scheduler-neutral resource mapping to SBATCH fields for CPU, memory, GPU,
  and wall time.
- Single-job script generation where one SLURM allocation runs the whole
  pipeline.
- Afterok script generation where one job per runnable stage uses scheduler
  dependency edges.
- Dry-run manifest files under the run directory with planned jobs, scripts,
  dependencies, resources, and worker commands.
- CLI integration for selecting SLURM dry-run planning and printing generated
  script paths.
- Preflight checks for SLURM profile validity, resource mapping support,
  shared-run-directory assumptions, and optional command availability when
  known.
- Fake-command and pure unit tests for script generation and dependency
  construction.

Exit criteria:

- A user can generate reviewable SLURM scripts and manifests for a planned run
  without calling `sbatch`.
- Generated scripts invoke the v5 stage worker or whole-run entry points rather
  than duplicating execution logic.
- Resource mapping failures are reported before submission.

Defer:

- Live submission, scheduler polling, cancellation, recovery after partial live
  submission, controller mode, job arrays, MPI, remote stores, and containers
  inside SLURM.

Primary feature docs:

- `slurm.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `cli.md`
- `run-store.md`
- `testing.md`

## v7 - SLURM Operations

Goal:

- Add optional live SLURM submission and operational commands over the stable
  script/submission model.

Implement:

- `sbatch --parsable` integration, job ID parsing, command recording, and
  redacted submission metadata.
- Partial-submission failure handling with explicit submitted, skipped, and
  failed job records.
- SLURM stdout/stderr log path conventions under the run directory.
- `squeue`/`sacct` status integration where available, with capability-aware
  fallbacks.
- `scancel` cancellation support for submitted jobs.
- CLI integration for submission, job IDs, status, cancellation, and JSON
  output.
- Preflight checks for `sbatch`, optional status commands, profile-required
  fields, and writable submission/log directories.
- Fake-command tests for submission parsing, status mapping, cancellation,
  command failures, and partial-submission recovery.

Exit criteria:

- A user can submit, inspect, and cancel a small SLURM run in environments where
  SLURM commands are available.
- Default tests still do not require a real SLURM cluster.
- All live scheduler facts are persisted as provenance or state, not only
  printed to the terminal.

Defer:

- Controller-mode SLURM, job arrays, multi-node MPI orchestration, automatic
  retry classification from accounting state, remote stores, distributed locks,
  and containerized SLURM jobs.

Primary feature docs:

- `slurm.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `cli.md`
- `run-store.md`
- `state.md`
- `provenance.md`
- `testing.md`

## v8 - Run Catalog And Comparison

Goal:

- Make many local runs discoverable, searchable, and comparable through a
  rebuildable derived catalog while keeping the run store authoritative.

Implement:

- `RunSummary`, artifact summary, catalog index, and catalog warning models.
- Local run collection scanning based on run-store markers and metadata.
- Rebuildable sidecar catalog index with direct-scan fallback.
- `loom runs index` or equivalent rebuild command.
- `loom runs list` with core filters such as status, tag, fingerprint, commit,
  stage status, and JSON output.
- Stale-index detection and visible warnings for invalid, unreadable, partial,
  or disappeared runs.
- Metadata-only run comparison using config fingerprints, pipeline
  fingerprints, stage status, stage fingerprints, artifact identities,
  checksums, executor identities, and selected provenance facts.
- CLI command for metadata diff with human and JSON output.
- Tests with temporary run collections, synthetic run stores, stale indexes,
  invalid directories, and comparison fixtures.

Exit criteria:

- A run collection can be indexed, listed, filtered, and rebuilt from local run
  directories.
- Two runs can be compared without loading domain artifact payloads.
- The catalog remains derived data; the run store stays authoritative.

Defer:

- Export/import bundles, sweeps, dashboard UI, remote catalog services,
  domain-specific artifact diffs, and incremental watchers.

Primary feature docs:

- `run-catalog.md`
- `run-store.md`
- `artifacts.md`
- `provenance.md`
- `cli.md`
- `testing.md`

## v9 - Persistence And Concurrency Foundation

Goal:

- Revisit and strengthen Loom's authoritative persistence, lifecycle, and
  backend capability contracts before large concurrent execution, distributed
  sweeps, shared filesystems, and remote-capable stores depend on the current
  single-writer local-run assumptions.

Implement:

- A detailed implementation plan quality gate for the run-store, state,
  execution, reliability, sweep, remote-store, and run-catalog implications of
  concurrency.
- Backend capability models for authoritative run-state stores, including
  atomic status transitions, stage attempt allocation, stage/run leases,
  output commit semantics, consistent snapshot reads, collection listing, and
  freshness or revision evidence for query projections.
- A SQLite-first authoritative coordination backend and hard swap-over for
  active run state, keeping the public contract backend-neutral so stronger
  backends can replace SQLite later.
- Explicit stage-attempt and output-commit records that make committed outputs,
  failed attempts, interrupted attempts, retries, and cleanup candidates
  unambiguous.
- A clarified run lifecycle for concurrent DAG execution where the run status is
  a materialized lifecycle summary over stage, attempt, lease, and commit facts.
- A clarified stage lifecycle for `READY`, claimed/leased, running/submitted,
  committing, succeeded, failed, cancelled, interrupted, and retryable states
  without widening core status enums before the state model is reviewed.
- Artifact-index concurrency rules, likely by making per-stage committed
  artifact facts authoritative and treating run-level artifact indexes as
  materialized views unless a backend can update them transactionally.
- Active-query rules for `RunCatalog` and CLI/status consumers so derived
  SQLite catalog rows, status summaries, and future sweep tables validate
  against authoritative freshness or revision evidence.
- A bounded user-facing parallel stage execution policy over independent ready
  DAG stages, exposed through both Python API and CLI, and gated on backend
  capabilities. Parallel execution is opt-in, serial execution remains the
  default, and failure behavior is configurable between stopping new leases
  after a terminal stage failure and continuing independent non-dependent DAG
  branches. Explicit parallel requests fail loudly when required backend
  capabilities are unavailable.
- A minimal backend inspection/debugging CLI that reads authoritative backend
  state under `loom backend ...` and does not mutate, repair, export, or
  snapshot backend state.
- Sweep coordination requirements for future large sweeps: trial manifests,
  trial claim/lease records, trial retry attempts, global concurrency leases,
  named resource slot leases, status snapshots, and abandoned-lease recovery.
- Backend capability assessment that identifies which guarantees are safe for
  the SQLite-first backend, which assumptions are unsafe on shared filesystems
  or remote-capable stores, and which capabilities require a stronger future
  backend.
- Contract tests using synthetic local and fake/conformance backends for
  supported and unsupported capability behavior.

Exit criteria:

- Loom has a reviewed authoritative persistence contract that can support
  concurrent stage writers without making v8 catalog SQLite or any external
  tracker a second source of truth.
- New active runs use the SQLite-first authoritative backend for live state;
  legacy local state files are not live truth or fallback truth, and no user
  setup is required to select the new backend.
- Future parallel DAG execution can be capability-gated on atomic stage claim,
  attempt allocation, output commit, and recovery behavior.
- Bounded user-facing parallel stage execution is available through Python API
  and CLI for capability-supported local execution.
- Future large concurrent sweeps can build on explicit trial and resource lease
  semantics instead of ad hoc directory scans.
- Active run and sweep queries have a documented current-read guarantee or a
  documented warning path when the selected backend cannot provide it.

Defer:

- Full distributed workflow-engine behavior, hosted tracking services, remote
  catalog services, dynamic DAG mutation, adaptive sweep algorithms, concrete
  cloud backends, service-specific telemetry sinks, and domain-specific metric
  stores.
- Distributed or scheduler-backed parallel execution policy, full arbitrary
  shared-filesystem support, full remote backend or object-store authority, and
  Postgres/service backend implementation.
- Old-run migration, legacy local-file state fallback, and derived state
  export/snapshot commands. Derived export/snapshot behavior belongs in later
  bundle/export work if needed.
- Backend repair or mutation commands outside normal execution APIs.

Primary feature docs:

- `run-store.md`
- `state.md`
- `execution.md`
- `reliability.md`
- `run-catalog.md`
- `sweeps.md`
- `remote-stores.md`
- `artifacts.md`
- `runtime-resources.md`
- `slurm.md`
- `testing.md`

Planning notes:

- `docs/roadmap/stage-9/planning.md`

## v9-post - Authority-Backed Runtime Unification

Goal:

- Close the post-v9 local-store escape hatches so every active run and stage
  mutation enters through authority-backed store contracts, and define the
  service/database authority backend needed for multi-host and
  concurrent-controller operation.

Implement:

- A clear deprecation plan for `LocalRunStore` as a runtime entrypoint while
  keeping local path/materialization helpers for artifacts, logs, config
  snapshots, provenance, worker handoff files, and artifact/directory access.
- A comprehensive inventory of every current `LocalRunStore` runtime mutation
  entrypoint, plus a migration map for runtime paths, authority read paths,
  and local artifact/materialization helpers.
- A rename or split of useful local-run-directory machinery so local
  materialization cannot be mistaken for active lifecycle authority, likely
  around run-level and stage-level artifact/materialization interfaces.
- A documented run lifecycle over authority facts: run allocation/open,
  controller lease, guarded run status transitions, submitted state,
  cancellation/interruption, finalization, revisioned snapshots, and recovery
  diagnostics.
- A documented stage lifecycle over authority facts: stage plan action, attempt
  allocation, stage lease and fencing token, running/submitted state, output
  commit, terminal status, failure/blocking, retry eligibility, and cleanup
  candidates.
- Mandatory authority-backed runtime store construction for `PipelineRunner`
  and public Python examples.
- Authority-backed CLI mutation paths for `loom run`, SLURM dry-run/live
  submission, `loom stage run`, `loom stage-job run`, and prepared-run
  continuation.
- Fenced submitted-job and worker finalization so a worker can write local
  handoff files only as materialization and cannot commit stage success without
  active authority.
- A public store-interface decision where `RunStore` manages runs, run-level
  leases, run lifecycle, submitted operations, and access to scoped
  `StageStore` handles, while separate workspace/coordination surfaces are
  reserved for non-run sweep/resource concerns.
- A generic authority interface and conformance harness before concrete backend
  work, covering run lifecycle, stage lifecycle, leases, fencing, submissions,
  commits, snapshots, and recovery.
- A service/database backend implementation path for concurrent terminals,
  multi-host workers, and HPC submitted jobs, including declared consistency
  guarantees, lease/fencing behavior, and failure-closed mutation.
- Explicit HPC deployment and fallback capability profiles so the plan does
  not assume long-running login-node processes or compute-to-login networking.
  Fallback modes such as deferred finalization preserve authority-backed
  lifecycle commits while declaring weaker live-worker semantics.
- A separate system-wide backend adoption/refactor path after the concrete
  backend exists, covering runner construction, public factories, CLI
  commands, workers, SLURM planning/submission/cancel/status, status/catalog,
  plan, diagnostics, preflight, configuration propagation, examples, and tests.
- Capability diagnostics for embedded SQLite, local service, and future remote
  service authority backends, especially around multi-host consistency,
  transaction isolation, lease time, recovery scans, and stale writer fencing.
- Strict capability admission before concurrent stages, concurrent run
  submission, multi-host workers, live submitted-job commits, sweeps, or shared
  resource coordination are allowed.
- A hard deprecation and removal path for embedded run-local SQLite authority
  once the revised service/database backend satisfies the runtime authority
  contract. Derived catalog SQLite sidecars remain separate rebuildable
  projections.
- Tests proving local-only mutation is rejected for new runtime paths, local
  directory access cannot read or write lifecycle behavior, and
  authority-backed lifecycle transitions cover serial, parallel, subprocess,
  submitted, and worker-continuation flows.

Exit criteria:

- No supported mutating entrypoint creates or resumes a run through
  `LocalRunStore` alone.
- New runs always have authoritative attempt, lease, commit, revision, and
  snapshot state.
- Direct Python API docs and examples teach the authority-backed store factory,
  not `LocalRunStore`.
- SLURM and stage continuation flows are authority-backed or fail loudly when
  authority is unavailable.
- The concrete service/database backend is implemented, proven against the
  authority conformance harness, and supported by runtime/read systems through
  the public factory/configuration path.
- HPC deployment diagnostics distinguish managed service, allocation-scoped
  service, direct transactional database, co-located single-process, and
  deferred-finalization profiles.
- Unsupported concurrency modes fail before worker launch or scheduler
  submission rather than falling back to weaker local lifecycle behavior.
- The roadmap and planning notes state that embedded run-local SQLite authority
  is transitional and is removed from supported runtime behavior after the
  service/database backend lands.

Defer:

- Deleting local materialization files and helpers.
- Hosted production service deployment, authentication, authorization,
  tenancy, and operations.
- A distributed scheduler, queue, worker-daemon, or workflow engine.
- Migration or lifecycle interpretation of old local-only v0-v8 run
  directories.
- Full sweep runner behavior, remote artifact payload movement, and remote
  object-store authority.

Primary feature docs:

- `run-store.md`
- `state.md`
- `execution.md`
- `reliability.md`
- `resume.md`
- `remote-stores.md`
- `sweeps.md`
- `run-catalog.md`
- `slurm.md`
- `cli.md`
- `testing.md`

Planning notes:

- `docs/roadmap/stage-9-post/planning.md`

Implementation plan:

- `docs/roadmap/stage-9-post/implementation-plan.md`

## v10 - DB-Backed Service Supervisor And Offline Authority Import

Goal:

- Replace the v9-post in-memory co-located authority default with an
  operationally clear, DB-backed authority server plus supervisor that manages
  durable run lifecycle, stage lifecycle, and generic workspace coordination
  across commands, controllers, workers, and submitted jobs.

Implement:

- A DB-backed `AuthorityServer` implementation where clients and workers talk
  only to the authority API and never open the authority database directly.
- An `AuthoritySupervisor` responsible for server start, stop, health checks,
  stale-process detection, endpoint/auth metadata, registry updates, and
  cleanup.
- A workspace/allocation-scoped service registry that records the selected
  authority endpoint, workspace id, database location or service reference,
  process identity where applicable, service generation, health metadata, and
  redacted diagnostics.
- Strict authority resolution shared by Python API, CLI, subprocess workers,
  stage jobs, SLURM planning/submission/cancel/status, continuation commands,
  diagnostics, and preflight:
  - connect to an explicit endpoint or registry-discovered service and fail
    closed when unavailable;
  - run offline only when explicitly requested and record import evidence;
  - start local service infrastructure only through explicit supervisor
    lifecycle commands or trusted API calls;
  - reject silent creation of unrelated in-memory services for production-like
    entrypoints.
- Full conversion of production-like lifecycle-mutating runtime paths to the
  authority-first structure, including `loom run`, Python execution helpers,
  `PipelineRunner`, worker entrypoints, `loom stage run`, `loom stage-job run`,
  prepared-run continuation, SLURM live submission/cancel/status mutation paths,
  offline evidence creation, offline import, diagnostics, and preflight.
- Clear separation between authority-backed lifecycle mutation and read-only
  local inspection. Local log, artifact, config, provenance, and catalog
  inspection can remain file-backed when it is explicitly read-only and labels
  materialized/evidence state rather than authoritative service state.
- Clear user-facing modes for online service-backed execution and explicit
  offline-first execution, with any local service startup treated as
  supervisor-managed online infrastructure rather than an implicit runtime
  fallback.
- Persistent run lifecycle and stage lifecycle storage covering run admission,
  controller leases, run transitions, attempts, stage leases, fencing,
  submitted operations, output commits, artifact facts, snapshots, recovery,
  cleanup candidates, and audit events.
- Authority-backed `WorkspaceCoordinationStore` behavior for generic
  workspace/trial references, global counters, named resource limits, resource
  leases, and cross-run recovery scans, without implementing sweep scheduling in
  the authority server.
- A resource coordination port exposed through the authority client where online
  runners acquire generic named resource leases from the authority server before
  launching admitted work.
- A run-local offline resource coordinator for offline-first execution that can
  enforce limits within one run and records that no cross-run resource guarantee
  existed.
- Scheduler-ready request and decision value objects so a future
  `WorkflowScheduler` can optimize run/stage starts through authority APIs
  without opening the authority DB or replacing the runner/executor boundary.
- Admission and diagnostics that distinguish per-run lifecycle authority from
  cross-run workspace coordination capabilities.
- Documented run and stage lifecycle state diagrams with guarded transition
  rules, terminal-state policy, and clear ownership of who requests versus who
  accepts each transition.
- Lifecycle policy that treats interrupted stages as restart-from-scratch on
  resume, permits `SUBMITTED -> RUNNING` only when Loom regains active execution
  control after external scheduler acceptance, and converts accepted offline
  import evidence into authority-owned truth.
- True offline run import: a run may execute with no authority-created
  run/stage/attempt first, persist an offline execution evidence record, and
  later import into authority only after an equivalence and conflict check.
- Offline evidence schemas for execution plan, config/provenance, run URI,
  stage order, stage attempts, input fingerprints, output refs, artifact
  checksums where available, failure records, logs, runtime metadata, and
  provenance summaries.
- An authority import transaction that either creates an imported authoritative
  run with equivalent lifecycle facts or rejects the import with actionable
  diagnostics for conflicts, missing evidence, changed fingerprints, missing
  payloads, unsafe paths, or incompatible schema versions.
- Tests for service registry safety, connect-or-fail behavior, explicit
  offline-first execution, explicit supervisor startup, supervisor
  restart/health behavior, concurrent commands sharing a service, DB durability
  across service restart, service-backed workspace coordination, offline import
  acceptance/rejection, and no direct DB client bypass.

Exit criteria:

- Every production-like lifecycle-mutating entrypoint resolves authority through
  the shared online/offline policy before changing run, stage, attempt, lease,
  resource, or workspace coordination state.
- No converted runtime entrypoint writes lifecycle truth directly to a local run
  store except through explicit offline evidence creation or authority import.
- Read-only local inspection commands do not mutate lifecycle records and make
  clear whether they are reading authoritative service state or local
  materialized/evidence state.
- Runtime entrypoints no longer silently create an in-memory or DB-backed
  authority service as a fallback from execution.
- Missing or unreachable online authority fails by default with guidance for
  service startup/configuration and explicit offline-first execution.
- Independent commands in the same workspace/allocation discover or receive the
  same durable service endpoint and authority generation.
- A stopped or unreachable configured service produces clear fail-closed
  diagnostics before lifecycle mutation.
- Authority server state survives process restart through the selected DB
  backend.
- Concurrent controllers can create and mutate distinct runs against the same
  service without sharing per-run lifecycle accidentally.
- Concurrent stages in one run are still scheduled by the runner but fenced and
  committed by the authority server.
- Workspace coordination for sweeps, global counters, and shared resource
  limits is available through generic authority-backed coordination primitives
  rather than a separate client-opened SQLite coordination store.
- Online resource limits are enforced through authority-backed generic resource
  leases. Offline-first runs enforce only run-local limits and report the absence
  of cross-run resource guarantees.
- The authority server does not directly schedule DAG stages, sweep trials, or
  pipelines in v10; scheduler-ready request/decision data leaves room for a
  future `WorkflowScheduler` to optimize these starts through authority APIs.
- Offline-first runs can be imported into authority only when Loom can prove
  equivalence of plan, inputs, outputs, and persisted evidence.

Defer:

- Hosted production operations, authentication, authorization, tenancy, and
  high availability beyond the minimum supervisor contract.
- Compatibility support or migration for old implicit local-only runtime
  behavior.
- A full online `WorkflowScheduler`, distributed queue beyond the v11 whole-run
  queue, worker daemon, adaptive sweep runner, or external orchestration system.
  V10 reserves scheduler-ready interfaces but does not implement global
  scheduling policy.
- Remote artifact payload movement and remote object-store authority.
- Cryptographic attestation or signing for offline evidence.
- Domain-specific metric equivalence, artifact interpretation, or report
  generation.

Primary feature docs:

- `run-store.md`
- `state.md`
- `execution.md`
- `reliability.md`
- `resume.md`
- `remote-stores.md`
- `sweeps.md`
- `run-catalog.md`
- `slurm.md`
- `preflight.md`
- `cli.md`
- `testing.md`

Planning notes:

- `docs/roadmap/stage-10/planning.md`

## v11 - Queued Run Dispatch And Resource Pools

Goal:

- Let users enqueue many independent Loom whole-run requests and dispatch them
  through a dependency-light, workspace-scoped queue service that works in
  local, workstation, lab-server, and restricted HPC environments.

Implement:

- A durable queue service with SQLite-backed queue state for pools, one FIFO
  queue per pool, queue items, claims, dispatch handles, cancellation records,
  and audit records.
- Python APIs and trusted project config loading for defining queue pools,
  queue defaults, launch adapters, and enqueueing run intents.
- A run-intent snapshot and launch contract that records config identity,
  runtime options, queue metadata, idempotency facts, and required
  remote/bundle interface expectations at enqueue time.
- Resource-pool reconciliation where queue records store desired configuration
  only; authority-backed resource limits and active leases remain the source of
  truth before managed dispatch starts work.
- Managed resource mode that acquires authority-backed generic resource leases
  before local managed launches.
- Delegated scheduler mode for adapters such as SLURM where downstream
  scheduler acceptance, status, and cancellation facts are recorded without
  double-leasing Loom resources by default.
- Built-in launch adapters for local process execution and SLURM submission,
  both fakeable in default tests.
- A daemon-first long-running controller mode plus a foreground drain
  compatibility mode for restricted environments. Foreground drain must not
  orphan locally managed active work.
- Queue status vocabulary that distinguishes `queued`, `blocked`, `claimed`,
  `dispatching`, `active`, `completed`, `failed`, `cancelled`, and
  `cancel_unknown`, while linking to authoritative run or submitted-operation
  facts when available.
- Accurate cancellation reporting for every included adapter: the queue never
  claims cancellation success without proof, and unreachable or unverifiable
  outcomes remain visible as unknown.
- A minimal scheduler-policy interface whose first implementation selects the
  oldest eligible item in the pool's single FIFO queue. Priorities, fair
  sharing, and resource-dependent ordering remain future scheduler policy.
- Minimal CLI and supervisor surfaces for queue status, foreground drain,
  service start/stop where applicable, and cancellation, with Python APIs
  remaining primary for queue definition and enqueueing.
- Unit, contract, fake-adapter, and e2e-style tests that do not require real
  clusters, containers, brokers, or network services by default.

Exit criteria:

- A user can define a pool such as "1 GPU and X CPUs", enqueue many whole-run
  intents, and let Loom dispatch them FIFO subject to authority-backed leases or
  delegated scheduler acceptance.
- Queue service code does not open authority private storage or become the
  source of truth for run lifecycle, stage lifecycle, resource limits, or active
  leases.
- Queue state remains scheduling policy and operational audit data, not core
  `RunStatus` truth.
- Local and SLURM fake adapters prove launch, status, and cancellation
  behavior, including `cancel_unknown` reporting.
- Remote or pre-staged launches record which launch-interface checks were
  proven, unavailable, or delegated to later bundle/transfer support. V11 does
  not claim full remote workspace equivalence without v12 evidence.
- Default validation remains dependency-light and works without Redis,
  RabbitMQ, Kubernetes, Docker, Ray, Prefect, cloud services, or a real SLURM
  cluster.

Defer:

- Per-stage global scheduling, cross-run dependency graphs, multiple queues per
  pool, priority/fair-share/quota borrowing, preemption, resource-dependent
  queue ordering, adaptive retry, and worker health orchestration.
- Mandatory external orchestrators or brokers such as Redis, RabbitMQ,
  Kubernetes, Docker, Ray, Prefect, or cloud batch services.
- Full run bundle transport, remote artifact payload movement, and proof of
  complete remote workspace equivalence. These move to v12 bundle/transfer
  work.
- Hosted multi-tenant queue operations, authentication, authorization, high
  availability, and web dashboards.

Primary feature docs:

- `execution.md`
- `runtime-resources.md`
- `run-store.md`
- `state.md`
- `slurm.md`
- `preflight.md`
- `cli.md`
- `testing.md`
- A new queue/workflow-scheduler feature doc if the implementation plan needs a
  dedicated durable contract reference.

Planning notes:

- `docs/roadmap/stage-11/planning.md`

## v12 - Run Bundles, Transfer, And Exporters

Goal:

- Provide a safe archive and transfer path for local run metadata and selected
  payloads, define the transfer-interface evidence that v11 remote/pre-staged
  launchers need for stronger equivalence checks, and add a small
  compatibility-export surface for projecting completed runs into external
  tools without making those tools authoritative.

Implement:

- Run bundle manifest model with format version, entry records, checksums, and
  payload selection metadata.
- Manifest extension fields that can later preserve non-local artifact refs as
  opaque metadata without requiring remote credentials, backend validation,
  external-location validation, or payload downloads before the v15 external
  artifact contract exists.
- Run exporter result models and a minimal `RunExporter` protocol for
  post-run, explicit export operations over completed run metadata, bundle
  manifests, and selected payload references.
- Bundle/transfer interface records for config identity, required files,
  workspace roots, artifact payload expectations, environment prerequisites,
  schema compatibility, and verification evidence that queue launchers can
  reference instead of relying only on shared-workspace convention.
- Metadata-only export by default using standard-library archive support.
- Explicit artifact/log inclusion flags and size/path reporting.
- Path traversal, symlink, partially written run, and missing-payload safety
  checks.
- Bundle inspection without extraction.
- Import into a local run collection with manifest validation, checksum
  verification when requested, safe path handling, and catalog stale marking.
- Compatibility exporter hooks that can be reused by later plugins such as
  MLflow, DVC, W&B, HTML/static reports, or archival manifest writers without
  requiring those integrations in core.
- CLI commands for export, inspect, and import.
- Tests for manifest creation, metadata-only bundles, exporter result
  serialization, payload selection, unsafe path rejection, inspect without
  extraction, and import into a temporary run collection.

Exit criteria:

- A run can be exported, inspected, and imported without executing project
  code.
- Queue-driven remote or pre-staged launches can point to concrete
  bundle/transfer verification evidence before claiming a remote workspace
  matches the queued run intent.
- The default export path is conservative and does not unexpectedly include
  large payloads.
- Bundle manifests do not preclude later metadata-only external or remote refs,
  while v12 avoids claiming backend semantics before the v15 interface contract.
- Exporter contracts operate on persisted run metadata and artifact references,
  not project-specific metric semantics or artifact payload interpretation.
- Bundle safety checks are covered by focused tests.

Defer:

- Signed bundles, large payload deduplication, cross-machine catalog
  synchronization, bundle encryption, service-specific exporter
  implementations, automatic post-run exporter dispatch, and domain-specific
  comparison reports.

Primary feature docs:

- `run-catalog.md`
- `run-store.md`
- `artifacts.md`
- `io.md`
- `cli.md`
- `testing.md`

## v13 - Deterministic Sweeps

Goal:

- Support repeated experiments as deterministic collections of ordinary `loom`
  runs.

Implement:

- `SweepSpec`, `TrialSpec`, sweep manifests, trial manifests, and stable
  directory layout.
- Grid sweep expansion, manual trial expansion, deterministic trial IDs, stable
  trial ordering, and trial override generation through config APIs.
- Plan-only mode that writes or prints the resolved trial set.
- Sequential trial execution through `PipelineRunner` using normalized runtime
  options.
- Basic trial status aggregation from run stores and catalog-compatible
  summaries.
- Generic result collection starting with artifact refs and simple metadata,
  not domain metric semantics.
- `loom sweep plan`, `loom sweep run`, `loom sweep status`, and basic
  `loom sweep collect`.
- Tests for deterministic expansion, stable IDs, override generation, manifest
  persistence, failed-trial visibility, status aggregation, and collection from
  synthetic runs.

Exit criteria:

- A user can define a grid or manual sweep, inspect the planned trials, run
  them sequentially, and see trial statuses.
- Every trial remains an ordinary run that v8 catalog and v12 bundle tools can
  inspect.
- Sweep logic does not implement its own config merge, stage execution, or
  scheduler submission behavior.

Defer:

- Bounded local concurrency, distributed sweep controllers, SLURM per-trial
  batch submission, failed-trial rerun policies, random search, Bayesian
  optimization, adaptive trial generation, early stopping, and domain-specific
  result aggregation.

Primary feature docs:

- `sweeps.md`
- `config.md`
- `pipeline.md`
- `execution.md`
- `run-store.md`
- `run-catalog.md`
- `artifacts.md`
- `provenance.md`
- `cli.md`
- `testing.md`

## v14 - Plugin Discovery

Goal:

- Let installed trusted packages contribute extensions explicitly without
  making discovery an import-time side effect.

Implement:

- Known entry point group constants for recipes, codecs, sources, executors,
  artifact store backends, run exporters, and event sinks.
- `PluginRecord`, `PluginLoadResult`, plugin errors, duplicate handling, and
  structured failure reporting.
- Generic entry point listing and loading through `importlib.metadata`.
- Recipe plugin loading into supplied recipe catalogs.
- Codec plugin loading into supplied codec registries.
- Source, executor, and store backend loading after corresponding registries
  exist.
- Run exporter plugin loading after the v12 exporter protocol exists.
- Event sink plugin listing, with registration deferred until the v20
  `RuntimeEvent` and `EventSinkRegistry` contracts are stable.
- Plugin provenance summaries for plugin names, packages, versions, groups, and
  load results.
- `loom plugins list` and `loom plugins check`.
- Preflight checks for requested plugin availability, duplicate registration,
  and failed loads.
- Tests with fake entry points and fake registries.

Exit criteria:

- Plugin discovery is explicit and deterministic enough for tests and
  provenance.
- Importing `loom` does not load arbitrary third-party plugin code.
- Recipe and codec plugins can extend v0/v2 behavior through public registries.

Defer:

- Plugin marketplace behavior, automatic installation, dependency resolution,
  version solving, remote indexes, sandboxing, and third-party command
  injection into the core CLI.
- Concrete Prefect, MLflow, DVC, W&B, OpenTelemetry, cloud, or notification
  integrations. This version should make those integrations discoverable later,
  not ship service-specific behavior.

Primary feature docs:

- `plugins.md`
- `config.md`
- `io.md`
- `execution.md`
- `remote-stores.md`
- `cli.md`
- `preflight.md`
- `provenance.md`
- `testing.md`

## v15 - External Artifact Interface Contract

Goal:

- Define backend-neutral artifact-store interfaces, external artifact refs,
  API/handler boundaries, capability records, and tests before selecting or
  shipping real remote backends, including future external-system-backed stores
  such as MLflow or DVC.
- Clarify how run catalogs and v12 bundle manifests preserve external and remote
  artifact refs as metadata without requiring credentials or payload
  materialization.
- Define explicit published-immutable artifact reuse so expensive dataset
  processing can be reused across runs when a project supplies a stable artifact
  key, checksum or fingerprint evidence, and validation policy.

Implement:

- External/remote-capable artifact-store API shape, including store config/ref
  value objects, handler registration boundaries, and operation result/error
  types for metadata checks, preflight, and unsupported payload movement.
- Multi-location artifact reference semantics that distinguish managed run
  artifacts, external immutable input artifacts, and published immutable outputs
  without requiring symlinks as the persisted contract.
- External input artifact registration from authored config or preflight
  resolution, including URI/path, artifact type, schema version, checksum when
  available, semantic fingerprint when supplied, immutability assertion, and
  project metadata.
- Published artifact registration contract for stage outputs written outside
  the run artifact root, including producer provenance, deterministic reuse key,
  checksum/fingerprint evidence, owner/retention hints, and validation policy.
- Explicit reusable artifact lookup API that can answer "is there a compatible
  immutable artifact for this key?" without making cross-run cache reuse a
  default planner behavior.
- Artifact-store capability model: readable, writable, listable,
  atomic-commit support, checksum verification, and delete support.
- Backend-neutral URI/config validation hooks and redaction helpers.
- Store registry and handler hooks compatible with v14 plugin loading.
- Fake external/remote artifact store or handlers for contract and preflight
  tests.
- Manifest-last commit expectations and metadata shapes for remote-like stores.
- Read-only store behavior for reference artifacts.
- Local staging and cache policy records, without making cache authoritative.
- Preflight checks for backend plugin availability, URI validity, credentials
  when cheaply checkable, read/write capability, and unsupported operations.
- Run catalog and bundle manifest semantics for metadata-only external and
  remote refs, including store kind, redacted URI, artifact identity, immutable
  reuse key, checksum and size fields, and capability hints when known.
- Compatibility notes for MLflow-backed and DVC-backed artifact stores as
  candidate adapters, constrained by the same capability model as cloud stores.

Exit criteria:

- Core tests can exercise external/remote store semantics through a fake backend.
- External and remote stores advertise capabilities rather than relying on
  assumptions about consistency, checksums, listing, or deletion.
- Bundle/export/import workflows can preserve external and remote refs as
  metadata and materialize them only when a later payload operation explicitly
  requests it.
- The planner can consume an explicitly configured immutable-artifact lookup
  result as a stage output reuse decision only after type, schema,
  checksum/fingerprint, and project-supplied key validation pass.
- No cloud SDK or concrete backend adapter becomes a hard dependency.

Defer:

- Real cloud backend adapters, remote payload export/import, implicit bundle
  downloads, credential refresh management, distributed caches, remote garbage
  collection, automatic global cache lookup for arbitrary stage outputs,
  partial stage reuse, cross-region replication, signed manifests, remote run
  catalog services, and first-party MLflow or DVC store implementations.

Primary feature docs:

- `remote-stores.md`
- `artifacts.md`
- `io.md`
- `plugins.md`
- `preflight.md`
- `run-catalog.md`
- `reliability.md`
- `testing.md`

## v16 - Artifact Payload Materialization

Goal:

- Add explicit local, external, and remote artifact payload materialization and
  publish paths after the interface contract is stable, while keeping real
  backend dependencies optional.

Implement:

- Explicit local copy/link, external publish, and remote payload
  upload/download paths where backend capabilities support them.
- Checksum verification and clear unsupported-operation errors for local,
  external, and remote payload movement.
- Local staging lifecycle records for external publishes, remote writes, and
  downloads.
- Bundle export support for explicit external/remote payload materialization
  when requested.
- Import support that can preserve metadata-only external and remote refs
  without requiring credentials.
- At most one optional backend adapter family in the detailed plan, only if a
  concrete downstream need selects it.
- Plugin packaging and tests that keep optional backend dependencies outside
  the core package.
- Fake-backend tests for all core behavior and opt-in integration tests for
  any selected real backend.

Exit criteria:

- External and remote refs can be preserved in metadata-only workflows and
  materialized only when explicitly requested.
- Optional backend dependencies remain isolated from the default install.
- The detailed plan either selects one backend family or explicitly skips this
  step until one is needed.

Defer:

- Broad S3/GCS/Azure/MLflow/DVC parity, remote tracking services, distributed
  locking, global content-addressed caches, credential lifecycle management,
  signed manifests, and remote run catalog services.

Primary feature docs:

- `remote-stores.md`
- `artifacts.md`
- `io.md`
- `plugins.md`
- `run-catalog.md`
- `preflight.md`
- `testing.md`

## v17 - Docker Container Executor

Goal:

- Add a Docker-based container executor that reuses the stage-worker and store
  contracts.

Implement:

- Shared container config models for image, workdir, mounts, environment, and
  resource mappings.
- Docker command builder and executor using the Docker CLI.
- Environment filtering and secret redaction for recorded commands.
- Mount validation, working directory validation, run-directory writability
  checks, and artifact-root mount checks.
- Image/runtime provenance, including Docker version and image digest when
  cheaply available.
- Container log, exit-code, timeout metadata where available, and failure
  integration with run stores.
- Preflight checks for Docker command availability, image reference presence,
  mount sources, required environment variables, and resource support.
- Fake-command tests for command construction, mount validation, environment
  filtering, redaction, resource flags, exit-code mapping, and provenance.

Exit criteria:

- A stage can run through Docker with the same declared inputs/outputs and run
  store semantics as local and subprocess execution.
- Docker failures are inspectable through existing diagnostics.
- No Docker SDK dependency is required for the initial implementation.

Defer:

- Image build commands, registry authentication helpers, Docker Compose,
  Kubernetes, automatic image pulls during preflight, image lock files,
  advanced GPU mapping, Apptainer/Singularity, and treating containers as a
  security sandbox for untrusted code.

Primary feature docs:

- `container-executors.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `provenance.md`
- `reliability.md`
- `testing.md`

## v18 - HPC Container Execution

Goal:

- Support Apptainer/Singularity and the common SLURM plus Apptainer execution
  path used on HPC systems.

Implement:

- Apptainer/Singularity command builder and executor using CLI tools.
- Runtime detection for `apptainer` and `singularity` command names.
- HPC-friendly bind mount validation and working directory behavior.
- Image/runtime provenance for Apptainer/Singularity version and image
  identity when cheaply available.
- Resource mapping behavior that composes with v4 resource requests and v6/v7
  SLURM options.
- SLURM plus Apptainer script composition after standalone SLURM and standalone
  container paths are stable.
- Preflight checks for command availability, image reference presence, bind
  mounts, run-directory writability, required environment variables, and
  scheduler/container compatibility.
- Fake-command tests for command construction, SLURM script composition,
  environment filtering, resource flags, and failure mapping.

Exit criteria:

- Apptainer/Singularity can execute stages through the same worker contract as
  Docker.
- A dry-run SLURM plus Apptainer script can be generated and inspected.
- Live SLURM plus Apptainer behavior reuses v7 submission paths rather than
  inventing a separate scheduler implementation.

Defer:

- MPI orchestration, multi-node container coordination, site-specific module
  loading, automatic image conversion, registry authentication, Kubernetes, and
  treating containers as a security boundary.

Primary feature docs:

- `container-executors.md`
- `slurm.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `provenance.md`
- `reliability.md`
- `testing.md`

## v19 - Reliability Policies And Transactions

Goal:

- Make retry, timeout, failure classification, status detail, stage-attempt
  transaction, and retry-safety decisions explicit and inspectable across
  executors.

Implement:

- Shared retry, timeout, failure-category, and reliability policy models.
- Status detail records that keep the machine policy status stable while adding
  human/debug fields such as lifecycle phase, reason code, and message. This
  should improve CLI, catalog, retry, and cancellation diagnostics
  without expanding core status enums for every backend-specific situation.
- Retry planning around safe output transactions and explicit idempotency
  assumptions.
- Retry decision records persisted in run stores.
- Timeout support where executors can enforce it, with warnings and metadata
  when they cannot.
- Explicit stage-attempt transaction records for begin, stage, commit, rollback
  or failure, and cleanup outcomes. These records define when staged artifacts
  become authoritative and when retry is safe.
- Global concurrency lease models for future sweeps and shared-resource
  environments, including named keys, slot counts, lease duration, renewal
  records, and explicit behavior when lease renewal fails. Reuse or harden
  existing authority/coordination lease contracts where they already satisfy
  this shape rather than inventing a parallel lease model.
- Preflight warnings for unsupported retry, timeout, transaction, and
  concurrency-lease policies.
- CLI inspection for reliability and transaction records where useful.
- Tests for retry boundaries, retry-disabled behavior, non-retryable validation
  failures, timeout metadata, unsupported timeout warnings, transaction
  transition records, status detail records, lease renewal behavior, and
  retry-safety behavior.

Exit criteria:

- Reliability policy decisions are recorded as data, not hidden inside executor
  control flow.
- Automatic retry is conservative and only occurs after a failed attempt with
  safe output transaction semantics.
- Timeout behavior is capability-aware across local, subprocess, SLURM, and
  container executors.
- Status detail and reason records explain state without replacing the stable
  run and stage status vocabulary used by planning and resume.
- Stage-attempt transaction records make committed outputs, failed attempts,
  retry eligibility, and cleanup candidates unambiguous.
- Global concurrency leases can be consumed by later bounded sweeps or external
  adapters without making v13 sweeps concurrent by default.

Defer:

- Runtime event grammar expansion, event sink contracts, plugin-discovered
  event sink loading, service-specific notifications and tracking sinks such
  as MLflow or W&B, distributed event streaming, cleanup and deletion
  operations, artifact retention policy, full run-collection garbage
  collection, advanced exponential backoff, retry budgets across runs, and
  resource-aware retry escalation.
- Worker-daemon prefetch, advanced scheduling, and worker-health orchestration
  beyond the v11 queue controller. V19 should stay focused on the durable
  reliability records and policies that orchestration adapters consume.

Primary feature docs:

- `reliability.md`
- `execution.md`
- `run-store.md`
- `state.md`
- `artifacts.md`
- `preflight.md`
- `cli.md`
- `testing.md`

## v20 - Runtime Events And Event Sinks

Goal:

- Add audit-ready runtime event records and observe-only event sink contracts
  over committed Loom facts without making observers part of execution
  correctness.

Implement:

- Event records for run and stage lifecycle events, submission events, retry
  decisions, timeout outcomes, stage-attempt transaction transitions, and
  plugin callback hooks.
- A structured event grammar for audit logs and event sinks: event id,
  sequence, occurred timestamp, event name, primary resource, related
  resources, payload, and optional causal predecessor. Local `events.jsonl`
  should remain append-only and machine-readable.
- Compatibility or versioning behavior for existing local event records and
  `events.jsonl` readers.
- Event payload shapes that include enough stable metadata for external
  tracking projections: run URI, stage name, status, timestamps, executor,
  artifact refs, fingerprints, submitted-operation IDs, retry/timeout
  decisions, transaction IDs, and selected provenance facts.
- `EventSink` and `EventSinkRegistry` contracts for observe-only callbacks over
  committed runtime facts. Event sinks may write external side effects or links
  back into run metadata through explicit store APIs, but they must not mutate
  plans, configs, artifacts, stage outputs, status transitions, retry
  decisions, transaction records, or core store records.
- Programmatic event sink registration first.
- Plugin-discovered event sink loading after the v14 plugin surfaces and this
  version's event sink registry are both stable.
- Callback failure records and default best-effort failure policy. A later
  strict mode may fail runs for audit-heavy deployments, but the default must
  not let observer failures change run correctness.
- Preflight warnings for unsupported event persistence, event sink
  registration, and callback failure policies.
- CLI inspection for event records where useful.
- Tests for event record serialization, event ordering after durable state
  transitions, event payload compatibility, event sink dispatch, plugin event
  sink loading, and callback failure behavior.

Exit criteria:

- Event records are suitable as an audit log: ordered, typed, resource-linked,
  and useful without importing project code.
- Event sinks are observer-only and cannot become an alternate execution,
  planning, artifact, retry, transaction, status, or metric semantics layer.
- Callback failures are visible and best-effort by default.
- Existing local event records have an explicit compatibility or versioning
  path.
- Plugin-discovered event sinks can be loaded only through explicit user or
  programmatic action.

Defer:

- Cleanup and deletion operations, artifact retention policy, full
  run-collection garbage collection, service-specific notifications and
  tracking sinks such as MLflow or W&B, distributed event streaming, strict
  audit-failure mode, retry budgets across runs, and resource-aware retry
  escalation.

Primary feature docs:

- `reliability.md`
- `execution.md`
- `run-store.md`
- `state.md`
- `preflight.md`
- `plugins.md`
- `cli.md`
- `provenance.md`
- `testing.md`

## v21 - Cleanup And Retention

Goal:

- Add conservative cleanup, retention, and garbage-collection operations without
  surprising deletion of user data.

Implement:

- Cleanup candidate models for loom-owned temporary files and failed-attempt
  artifacts recorded in metadata.
- Cleanup dry-run reporting and explicit deletion APIs.
- CLI cleanup commands with confirmation or programmatic delete intent.
- Path safety rules: managed roots only, metadata or marker ownership, symlink
  rejection, visible deletion failures, and no arbitrary directory guessing.
- Artifact retention metadata and inspection support.
- Retention modes such as keep, temporary, archive, and external as policy
  hints rather than automatic deletion commands.
- Conservative run-collection garbage collection for explicitly selected
  candidates.
- Preflight warnings for cleanup paths outside managed roots and retention
  policies unsupported by selected stores.
- Tests for cleanup dry-run, path safety, symlink rejection, deletion intent,
  retention serialization, GC candidate selection, and artifact ownership.

Exit criteria:

- Users can see what `loom` would clean before deletion.
- Actual deletion requires explicit intent and is limited to loom-owned paths.
- Retention metadata is visible to export/import and inspection workflows.

Defer:

- Automatic retention deletion, aggressive artifact garbage collection, global
  cache collection, organization-specific cleanup policies, remote service
  retention enforcement, and destructive cleanup without explicit user intent.

Primary feature docs:

- `reliability.md`
- `artifacts.md`
- `run-store.md`
- `run-catalog.md`
- `preflight.md`
- `cli.md`
- `testing.md`

## v22 - Examples And Validation Refinement

Goal:

- Make the functionality that actually exists easy to discover, run, and trust
  through robust examples, integration tests, end-to-end tests, and refined
  documentation.

Implement:

- A consolidated example inventory over `examples/` with stable example IDs,
  user-goal grouping, owning feature docs, owning roadmap stage, validation
  tier, and runnable/manual status.
- A manifest and README consistency pass for authoring, execution, operations,
  container, SLURM, authority, cleanup, retention, event, reliability, bundle,
  sweep, plugin, and artifact examples that exist by this point.
- Runnable examples that demonstrate implemented public Python APIs and CLI
  commands without domain-specific stages, real clusters, cloud services,
  network access, optional provider SDKs, or hidden generated state in default
  validation.
- Integration-test behavior that exercises examples against realistic local
  workflows, temporary run roots, authority modes, fake backends, and public
  command/API boundaries.
- End-to-end test behavior that proves representative user journeys across
  authoring, execution, operations, diagnostics, events, cleanup/retention, and
  export/import where those surfaces exist.
- Example validation coverage that checks runnable example manifests, README
  metadata, public API imports, command snippets where feasible, generated
  output boundaries, and stable failure behavior.
- Documentation updates that cross-link examples, feature docs, roadmap
  stages, integration/e2e coverage, validation tiers, and known manual example
  prerequisites.
- A final docs and example refinement pass that removes stale text, aligns
  example output and README claims with validated behavior, and records any
  examples that remain intentionally manual.

Exit criteria:

- Users can browse examples by goal and tell which examples are runnable by
  default, opt-in, manual, illustrative, or marked as `internal_demo`.
- Every runnable example has validation coverage and uses only generic,
  domain-neutral data.
- Integration tests cover example behavior through public APIs, fake/local
  backends, and realistic temporary run layouts.
- End-to-end tests cover representative CLI and Python workflows without
  requiring external services in the default suite.
- Every manual or illustrative example states why it is not part of default
  validation and what external capability it needs.
- Documentation claims for examples, integration behavior, and e2e behavior are
  backed by named validation paths or clearly marked as manual.

Defer:

- New runtime features, new executor/store/plugin behavior, domain-specific
  tutorial projects, hosted documentation publishing, website work, notebooks
  that require external kernels or services, large real-data examples, and
  broad generated-doc tooling beyond what is needed to validate the in-repo
  examples.
- Roadmap-planning cleanup passes. V22 may keep local notes in docs where they
  clarify an example, but its primary work is robust examples, integration/e2e
  validation, and documentation refinement.

Primary feature docs:

- `testing.md`
- `cli.md`
- `config.md`
- `pipeline.md`
- `execution.md`
- `run-store.md`
- `artifacts.md`
- `reliability.md`
- `preflight.md`
- `plugins.md`
- `remote-stores.md`
- Existing `*-example-coverage.md` documents.

Planning notes:

- `docs/roadmap/stage-22/planning.md`

Implementation plan:

- `docs/roadmap/stage-22/implementation-plan.md`

## v23 - Managed Local Concurrency And Resource Assignment

Status:

- Stage 23 implementation is complete. The narrowly scoped operational follow-up
  is tracked in the [Stage 23-post implementation plan](roadmap/stage-23-post/implementation-plan.md);
  it adds the managed-local runtime/recovery proof without reopening the
  completed Stage 23 plans.

Goal:

- Let one long-lived managed-local queue controller keep several whole-run
  items active in one selected pool, bounded by an opt-in controller limit,
  authority-backed scalar resource admission, and exclusive concrete resource
  assignments.
- Keep logical resource requests scheduler-neutral while giving local execution
  a generic, dependency-free way to bind authored concrete slots.

Implement:

- A pool-scoped controller cycle that reconciles every active item before
  filling available capacity, returns per-item outcomes, stops at explicit
  active and per-cycle budgets, and preserves the existing one-step
  `run_once()` behavior and effective default limit of one.
- Explicit started, synchronously completed, and deferred-before-start dispatch
  outcomes. Only typed temporary capacity exhaustion may defer; authority
  uncertainty and fencing loss fail closed rather than becoming queue retry
  policy.
- An atomic SQLite FIFO claim and guarded claim release, handle commit,
  completion, and cancellation transitions so stale controllers cannot mutate
  newer attempts. Deferral preserves enqueue order and dispatch attempt,
  clears the claim, records a safe reason code, and stops that FIFO for the
  current cycle.
- Stable structured coordination/admission failure kinds across in-memory,
  SQLite, and authority-service paths, replacing queue-side exception-message
  parsing.
- A narrow queue-local structural assignment-provider protocol with immutable
  requests and discriminated results. Core supplies no-op assignment and an
  ordered static-slot provider; downstream projects may inject discovery or
  site-placement implementations without moving scheduling correctness out of
  Loom.
- Static slots coordinated through existing named authority leases provisioned
  at limit one. Selection is deterministic, multi-slot requests use distinct
  slots, partial acquisition is compensated, and queue code never creates or
  mutates authority limits.
- Managed-local composition in the order drift validation, command
  normalization, scalar admission, concrete assignment, deterministic
  environment-list binding, process-group start, and durable safe evidence.
  Every failure and terminal path unwinds owned resources exactly once, and an
  unpersisted started process is terminated and observed before its resources
  can be reused.
- Live-owner lease renewal with a bounded safety deadline. Definitive ownership
  loss or an unresolved outage at the deadline stops filling and terminates the
  process group; resources are released only after exit is observed. A unique
  adapter-session identity prevents restarted or foreign controllers from
  treating unavailable in-memory process state as their own.
- Deterministic queue-owned stdout and stderr paths per item and attempt, plus
  one consistent repository pool snapshot and a redacted status model for text
  and JSON. Persisted output is limited to safe assignment labels, process
  facts, lease identifiers/timing, owner/session identity, and queue-relative
  log paths.
- Backward-compatible queue configuration with an explicit positive managed
  active limit, local static-assignment inventory, and environment-list binding
  configuration. Preflight validates inventory uniqueness, authority limits
  and capabilities, impossible requests, and binding conflicts without
  provisioning resources.
- Python-first construction and dependency-free fake/static integration and
  end-to-end coverage. Scheduling logic remains outside the CLI.

Exit criteria:

- Twelve queued commands over three generic static slots peak at exactly three
  active items under one controller, use unique slots, leave excess work
  queued, and refill one slot after success, failure, or cancellation.
- Concurrent SQLite controllers cannot claim one item twice or use a stale
  claim/handle to defer, complete, or cancel a newer attempt.
- Capacity shortage never becomes `FAILED` or `UNKNOWN`; invalid configuration
  fails before launch, and uncertain authority or ownership state prevents new
  work from starting.
- CPU-only, fake, synchronous, custom, and delegated SLURM adapters retain
  their existing behavior. `LaunchContract.resources` and queue items contain
  no concrete-resource or vendor-specific fields.
- Text and JSON status derive from the same read model and never reveal fencing
  tokens, command/cwd details, environment names or values, or provider-private
  payloads.
- Phase-targeted suites, `make validate-pr`, and `make test-summary` pass; a
  real accelerator profile remains manual and opt-in.

Defer:

- Dynamic inventory, vendor libraries, device health, topology, free-memory or
  utilization placement, and multi-host resource-instance coordination.
- Exact distributed enforcement of `max_active_items`. Atomic claims and
  authority resource leases are hard multi-controller safety boundaries; the
  item count is a single-controller policy in v23.
- Priorities, fairness, preemption, backfilling, starvation policy, multi-pool
  balancing, fine-grained stage scheduling, and general scheduler-policy
  plugins.
- Automatic retry, worker daemons, process watchdogs, controller heartbeats,
  process reattachment after controller death, and unconditional crash-time
  process termination guarantees.
- Provider registries, public provider recovery hooks, configurable external
  log paths, arbitrary launch rewriting, mounts, device nodes, and shell
  templating.
- Bulk submission CLI, a managed-local worker command, and downstream
  experiment, cache, artifact, metric, or report behavior.

Primary feature docs:

- `queue.md`
- `runtime-resources.md`
- `run-store.md`
- `cli.md`
- `testing.md`

Planning notes:

- `docs/roadmap/stage-23/planning.md`

Implementation plan:

- `docs/roadmap/stage-23/implementation-plan.md`

Phase execution plans:

- `docs/roadmap/stage-23/phases/safe-pool-cycles.md`
- `docs/roadmap/stage-23/phases/managed-local-assignments.md`
- `docs/roadmap/stage-23/phases/operator-status-proof.md`

## v24 - Operational Lifecycle And Recovery Validation

Status:

- Planning is confirmed and the two-phase implementation plan is ready. This
  stage follows the completed Stage 23-post managed-local runtime and precedes
  resource-aware queue selection.

Goal:

- Prove through real operating-system processes that Loom's durable lifecycle
  state agrees with what actually happened when work starts, stops, times out,
  is cancelled, or loses its coordinator or authority.
- Prove that interrupted or corrupt work never becomes a reusable success and
  that explicit resume recovers conservatively without hiding the earlier
  incomplete attempt.

Implement:

- One locked lifecycle outcome table across the runner, CLI, executors, queue,
  state, and resume behavior. Authored early stop and explicit cancellation are
  `CANCELLED`; caught keyboard interruption follows the serial/parallel rules
  below before CLI exit 130; ordinary exception or enforced timeout is `FAILED`;
  unclean loss becomes `INTERRUPTED` only when recovery authoritatively
  classifies the old active run.
- Runner-boundary keyboard-interrupt handling for serial, parallel, and
  prepared-worker paths. Serial/prepared work cancels its uncommitted active
  stage; parallel local execution stops new scheduling and settles already-
  running non-preemptible stages truthfully. The runner then cancels the run,
  unwinds owned resources, and preserves Python/CLI interruption behavior.
- Hermetic serial-local, parallel-local, and subprocess CLI tests that start a
  blocking domain-neutral stage, wait for a marker, deliver a real signal, and
  inspect exit code,
  authoritative run/stage state, reason evidence, process liveness, logs,
  artifact indexes, downstream state, locks, and leases. Subprocess coverage
  must prove the worker exits rather than only proving that Loom requested
  termination.
- A real enforced-timeout integration path using a sleeping stage and the
  production subprocess runner. It verifies durable timeout facts, non-zero
  execution outcome, worker exit, preserved logs, absent output commit, and a
  clean later attempt. Existing injected `TimeoutExpired` unit coverage remains
  the precise branch test.
- A real managed-local cancellation path complementing Stage 23-post's
  deterministic fake-process coverage. A blocking child must be observed dead
  before the queue item becomes `CANCELLED` and before scalar/member leases are
  released; queued and foreign-owner work must remain untouched.
- An unclean-loss scenario that kills only a test-owned coordinator/worker
  process tree after the stage-start marker. Before recovery, Loom must show no
  success, output index, or downstream start and must reject conflicting work
  while ownership is still live. After expiry, a newly exclusive controller
  must match authority recovery facts, record durable `INTERRUPTED`/stale events
  and transitions, and only then plan a new attempt that may publish outputs.
- Cross-backend proof that SQLite and the local service authority both reject a
  second unexpired controller lease, allow a fenced replacement after expiry,
  and preserve expired ownership as recovery evidence.
- Private controller-lease renewal while an authority-backed runner remains
  alive, with fail-closed renewal errors and no public run-lock API change.
- A service-authority loss scenario that stops the real local authority service
  while a blocking stage is active. Commit must fail closed: Loom may retain
  diagnostic files, but it cannot publish reusable success without authority,
  silently steal a valid lease, or start dependent work.
- A public resume scenario that corrupts the bytes of a successful local
  artifact. Checksum mismatch must rerun the producer and its consumers, reuse
  an unaffected branch, expose a stable reason, and restore agreement among
  payload bytes, stage outputs, and the run artifact index.
- Small reusable test-support helpers for marker creation, bounded condition
  waits, test-owned PID/process-group cleanup, and process-liveness assertions.
  They remain private to tests, add no runtime dependency, use no arbitrary
  fixed sleep as an oracle, and never operate on an unvalidated foreign PID.
- Lifecycle documentation that states the observable outcome and authoritative
  owner for each tested boundary. Validation checks each invariant where its
  dimensions causally interact instead of multiplying every executor, signal,
  store, and artifact case into a Cartesian matrix.

Exit criteria:

- A real Ctrl-C during local execution and during subprocess execution leaves
  the active stage and run `CANCELLED`, exits the CLI with 130, starts no
  downstream work, publishes no output, releases owned coordination only after
  cleanup, and leaves no worker process behind.
- A bounded-parallel local Ctrl-C stops new scheduling, lets already-running
  stages settle to their actual terminal state, blocks unresolved work, cancels
  the run, and exits 130 without relabelling valid committed success.
- A real subprocess timeout leaves the worker dead, the stage and run `FAILED`,
  durable timeout/log evidence present, and no committed output.
- Managed-local cancel is proven against a real child process: process exit
  precedes terminal item state and resource release, pending work stays queued,
  and foreign work is not mutated.
- An uncatchable process-tree loss cannot produce false success or reusable
  artifacts. Live ownership blocks conflict across both local authority
  backends; exclusive recovery plus matching scan facts records the interrupted
  run/stale attempt before a distinct successful attempt.
- Artifact checksum corruption is detected through a public run/resume path;
  the affected dependency branch reruns, the unrelated branch is reused, and
  the repaired payload and index agree.
- Real authority loss before commit fails closed and remains inspectable.
- Phase-targeted tests, `make validate-pr`, and `make test-summary` pass without
  requiring Docker, Apptainer, SLURM, external network access, or a new
  dependency.

Defer:

- Automatic process reattachment, PID-based adoption, unconditional cleanup
  after machine loss, a Loom daemon, worker pools, or a general process
  supervisor. External service managers remain responsible for containment.
- A public repair command, silent state repair, automatic lease stealing, or a
  new stage lifecycle status. The existing authority recovery transitions,
  attempt history, `STALE`, `CANCELLED`, and run-level `INTERRUPTED` vocabulary
  are sufficient for this stage.
- Graceful handling of every platform-specific signal, Windows process-control
  parity, scheduler preemption policy, automatic retry-policy changes, and a
  comprehensive backend-by-failure matrix.
- Real Docker, Apptainer, SLURM, GPU, scheduler-accounting, notification, and
  remote-service acceptance profiles. Stage 26 owns their environment gates,
  commands, evidence, and any runtime-specific strengthening.

Primary feature docs:

- `testing.md`
- `execution.md`
- `state.md`
- `reliability.md`
- `resume.md`
- `artifacts.md`
- `queue.md`
- `run-store.md`

Planning notes:

- `docs/roadmap/stage-24/planning.md`

Implementation plan:

- `docs/roadmap/stage-24/implementation-plan.md`

Phase execution plans:

- `docs/roadmap/stage-24/phases/real-interruption-and-cancellation.md`
- `docs/roadmap/stage-24/phases/crash-recovery-and-artifact-trust.md`

## v25 - Resource-Aware Whole-Run Queue Selection

Status:

- Planning is confirmed. Expanded design-safety review and the implementation-
  plan quality gate passed; both phases remain pending. Phase 1 follows Stage
  24, while its functional queue/concurrency base remains completed Stage 23.

Goal:

- Let a managed whole-run queue use a caller-provided candidate-selection
  policy so temporarily unusable FIFO-head work need not leave compatible
  capacity idle.
- Preserve strict FIFO as the default and keep queue mutation, resource
  authority, concrete assignment, and process lifecycle safety inside Loom.

Implement:

- A bounded, deterministic queued-candidate view containing only selection-safe
  identity, enqueue ordering, dispatch attempt, and scheduler-neutral logical
  resource amounts.
- A small queue-local structural selection-policy protocol that chooses one
  supplied candidate or stops with a safe reason code. Python constructor
  injection is the required extension path; missing injection uses the existing
  Stage 23 atomic FIFO path without a new policy object.
- Controller-local advisory logical availability and current-cycle attempt/
  deferral facts for resource-aware policies. Every selected item still passes
  authoritative scalar admission and Stage 23 concrete assignment before work
  starts.
- Atomic exact-candidate claims, bounded refresh after selection races, and
  policy-output validation. Project policy code never runs inside a SQLite
  transaction and cannot bypass active, dispatch, claim, lease, assignment, or
  process-safety guards.
- Policy-controlled bounded continuation after typed pre-start capacity
  deferral. FIFO retains Stage 23's stop behavior; an injected policy may try a
  different, previously unattempted candidate in the same cycle.
- Safe cycle and audit evidence containing the policy ID, selected item, and
  reason code without persisting full capacity snapshots or arbitrary
  policy-private state.
- A dependency-free downstream first-fit example and real SQLite queue/
  coordination tests for the two-unit FIFO head, one-unit later item, and one
  available unit scenario.

Exit criteria:

- Existing callers and delegated pools retain FIFO behavior without config or
  record migration.
- A Python caller can inject a managed-pool policy that starts the later
  one-unit item while the older two-unit item remains queued.
- Two controllers selecting the same candidate cannot both claim or launch it,
  and stale capacity observations cannot over-allocate authority or concrete
  slots.
- Candidate evaluation, claim refresh, deferral, and dispatch remain bounded,
  and one candidate is attempted at most once per cycle.
- Policy input and evidence contain no commands, environments, fencing tokens,
  concrete assignment state, or provider-private payloads.
- Phase-targeted tests, `make validate-pr`, and `make test-summary` pass.

Defer:

- A built-in non-FIFO fairness policy, starvation guarantee, durable aging or
  bypass counters, reservations, runtime estimates, priorities, and preemption.
- Multiple queues per pool, cross-pool fairness or balancing, distributed
  active-item quotas, automatic retry, and policy hot reload.
- Dynamic policy discovery, entry-point registration, and authored arbitrary
  class loading; custom policy composition remains Python-first.
- Concrete slot selection, vendor/device observation, and resource mutation by
  policy code. Stage 23 providers and authority leases retain those roles.
- Delegated scheduler ordering changes, universal workflow scheduling, and
  fine-grained pipeline-stage scheduling.

Primary feature docs:

- `queue.md`
- `runtime-resources.md`
- `testing.md`

Design guide:

- `docs/roadmap/stage-25/design-guide.md`

Planning notes:

- `docs/roadmap/stage-25/planning.md`

Implementation plan:

- `docs/roadmap/stage-25/implementation-plan.md`

Phase execution plans:

- `docs/roadmap/stage-25/phases/safe-resource-aware-selection.md`
- `docs/roadmap/stage-25/phases/bounded-head-bypass-proof.md`

## v26 - Downstream Operations Design

Goal:

- Turn downstream-usage questions into explicit design artifacts and
  roadmap-ready implementation choices without rewriting completed roadmap
  stages.

Implement:

- Stage-author guidance for the preferred artifact-directory workflow: use
  `StageContext.local_output_path(...)` or
  `StageContext.local_workspace_path(...)`, write outputs or temporary files
  there, then return refs from `save_artifact(...)` or
  `register_local_artifact(...)`. The guidance should make clear that stage
  code receives artifact refs, not mutable store handles, and that project code
  owns domain schemas.
- Logging guidance that distinguishes stage-owned log files from
  executor-captured stdout/stderr. It should document local, subprocess,
  container, and SLURM behavior where available, explain SLURM wrapper log
  paths, and describe what happens when project code configures Python logging
  itself.
- Queue and resource guidance that shows a managed local queue pool, a delegated
  SLURM queue pool, resource preflight, authority-backed resource leases, and
  the difference between scheduler-neutral resource requests and
  executor-specific resource mapping.
- Resource validation and usage-observation design. Loom already validates
  scheduler-neutral resource request shape, executor capabilities, SLURM dry-run
  mappings, queue managed-pool reconciliation, and authority-backed leases where
  those features exist. This stage should define observed usage records
  separately from requested allocation: scheduler accounting such as `sacct`,
  container process facts, GPU observations, allocation-versus-usage
  diagnostics, and policy for warnings or failures when usage evidence is
  missing or mismatched.
- Generic scheduling policy design. V10 reserves scheduler-ready request and
  decision records, v11 adds a narrow whole-run FIFO queue, v23 adds bounded
  managed-local reconciliation and concrete assignment, v24 proves operational
  lifecycle and recovery boundaries, and v25 adds only a
  queue-local whole-run candidate-selection seam. This stage should decide
  whether to introduce a broader scheduler interface over authority snapshots,
  resource leases, queue items, ready stage plans, and submitted operations.
  The same policy vocabulary should be adaptable to coarse whole-run scheduling
  and fine stage scheduling, but it must not replace the pipeline planner,
  authority store, executor contracts, queue audit records, v23 assignment
  lifecycle, or v25 queue-selection safety boundary.
- Public-interface compatibility review for scheduling and resources. Before
  implementation, review whether public `RunOptions`, `ExecutionPlan`,
  `StageExecutionRequest`, `ResourceRequest`, queue records, and authority lease
  APIs already carry enough information or need compatible additions.
- Stage reuse policy design. The current resume contract reuses a successful
  prior stage only when fingerprints and required artifacts remain valid, and
  project stages own checkpoint-level resume. This stage should decide whether
  to add a small planning policy such as `reuse_if_valid` by default,
  `always_run` for stages that must never reuse old outputs, or an explicit
  force/rerun policy surfaced through runtime options.
- Generic lifecycle notification design over event sinks. Core Loom should
  expose committed lifecycle events and observe-only sink contracts. This stage
  should define service-neutral notification messages, lifecycle alert filters,
  severity mapping, redaction rules, and a small notifier protocol, then define
  how Slack, Discord, webhooks, email, or tracking services adapt to that
  protocol through optional plugins.
- Full stage-scheduler requirements. Current SLURM `afterok` maps a planned DAG
  to submitted scheduler jobs, while v11 queues schedule whole runs. A future
  fine-grained stage scheduler would need authoritative ready-stage snapshots,
  per-stage resource admission, stage claim/fencing, submitted-operation
  recovery, cancellation semantics, retry/resume interaction,
  starvation/fairness policy, and evidence that local, subprocess, SLURM, and
  container executors can honor the same lifecycle handoff.
- Acceptance profiles with exact commands, environment gates, and receipts for
  default local tests, real containers, real SLURM, and future GPU-server,
  scheduler-accounting, queue-dispatch, and notification-plugin environments.
  Existing Docker and Apptainer availability/build smokes should grow into real
  Loom stage success/failure and artifact checks when those runtimes are
  available. Live SLURM coverage should verify artifact contents, dependency-
  failure behavior, and an actual scheduler-terminal cancellation rather than
  accepting a raced completion. The docs should state which suites are required
  by `make validate-pr`, which are summarized by `make test-summary`, and which
  remain scheduled or manual opt-in evidence.

Exit criteria:

- Downstream users have a concrete answer for where stage code writes outputs,
  how produced files are registered, how stdout/stderr and explicit logs are
  captured, and what remains project-owned behavior.
- Queue/resource documentation explains how queues are configured, what
  resources are admitted or mapped in local, SLURM, Docker, and Apptainer
  settings, and which resource checks are validation versus observed usage
  evidence.
- Scheduler planning distinguishes whole-run queue policy, submitted-executor
  behavior, fine-grained stage scheduling, and authority truth.
- Notification planning defines a generic observe-only protocol without making
  Slack, Discord, webhooks, email, or tracking services core dependencies.
- Resume planning either accepts the existing force/resume behavior or defines
  a compatible first-class per-stage reuse policy with clear fingerprint and
  artifact-payload boundaries.
- Acceptance-suite documentation covers currently implemented suites and names
  any future environment profiles without making them default PR gates. Any
  available real-runtime proof executes Loom behavior and inspects lifecycle,
  logs, and artifacts rather than checking only the external command version.

Defer:

- Implementing a generic scheduler, cross-pool queue policy, new notification
  adapter, new resource usage sampler, or new resume semantics until this design
  stage has produced a reviewed implementation plan. The bounded managed-local
  lifecycle assigned to v23 is not part of this deferral.
- Making real clusters, GPUs, containers, network services, or notification
  credentials required for default validation.
- Parsing domain metrics, checkpoints, or artifact payloads in core Loom.

Primary feature docs:

- `pipeline.md`
- `artifacts.md`
- `execution.md`
- `runtime-resources.md`
- `queue.md`
- `slurm.md`
- `container-executors.md`
- `resume.md`
- `reliability.md`
- `plugins.md`
- `testing.md`

Planning notes:

- To be created when stage planning begins.

## Deferred Integration Candidates

The items below are intentionally deferred until their owning contracts exist
and a downstream need justifies a design review. They should be treated as
future roadmap candidates, not as implicit scope for the versions above.

- MLflow event sink and run exporter plugins. A future adapter may create or
  attach to MLflow runs, log loom run URI, config and pipeline fingerprints,
  stage lifecycle facts, artifact references, and links to exported run
  bundles. Loom remains authoritative for stage status, artifacts,
  fingerprints, resume, and provenance. Core Loom should not become an MLflow
  tracking client or model registry.
- Prefect executor or orchestration adapter. The safest first candidate is a
  whole-run adapter where Prefect schedules or deploys `loom run` and Loom owns
  planning, resume, artifacts, and final run state. A later per-stage Prefect
  executor would need a separate design for attempt numbering, retries,
  cancellation, concurrency, and finalization before it can reuse the
  stage-worker contract safely.
- External work-pool and work-queue integrations beyond the v11 queue service.
  V11 owns Loom's dependency-light whole-run queue. Optional adapters for
  Prefect, Ray, Kubernetes, cloud batch systems, or other orchestrators should
  remain separate integrations over Loom queue/run contracts.
- Worker-daemon prefetch and advanced health-check orchestration beyond v23.
  Future controllers may pre-submit infrastructure before scheduled start time,
  heartbeat executor availability, refresh submitted-job status in richer ways,
  or add more advanced cancellation reconciliation, but those should not expand
  the bounded managed-local lifecycle stage.
- MLflow-backed and DVC-backed artifact stores. These should be optional
  plugin backends after the v15 remote-store capability model exists. They must
  advertise read/write/list/checksum/delete and transaction semantics like any
  other backend, and they must not become special cases inside core Loom.
- Hydra configuration or launcher bridges. Existing Hydra projects may benefit
  from a config frontend or launcher adapter, but any bridge must preserve
  authored-source provenance, fingerprints, and path-aware error behavior well
  enough for Loom resume decisions to stay trustworthy.
- OpenTelemetry, W&B, JSONL audit, webhook, or notification event sinks. These
  should be service-specific plugins over the v20 event sink model. Core Loom
  should provide the event contract and failure policy, not service delivery.
- No `MetricExtractor` layer. Loom may track a metrics file as an ordinary
  artifact reference because project code produced it, but core Loom should not
  parse metrics, define metric names, optimize metrics, query metrics, or infer
  experiment semantics. Project-owned code or external adapters may choose how
  to interpret artifacts outside Loom's core contract.

## Detailed Plan Drafting Checklist

Before turning any roadmap version into a full implementation plan:

1. Re-read the primary feature docs for that version and the feature docs it
   depends on.
2. Confirm the previous roadmap version has landed, or document the smallest
   compatible assumption if planning must start early.
3. Define public Python interfaces, CLI commands, persisted records, and file
   layout changes.
4. Identify dependency changes, optional extras, plugin boundaries, and import
   boundary risks.
5. List conflicts, tradeoffs, alternatives rejected, accepted debt, and revisit
   triggers.
6. Split the version if it contains unrelated adapters, multiple external
   systems, or more than one major persisted schema.
7. Break the version into implementation phases that can be reviewed
   independently.
8. Define default tests, fake-backend tests, opt-in integration tests, and
   checks that must pass before PR review.
9. Record branch, worktree path, plan quality gate status, assumptions, and
   reviewability notes in the expanded plan.
10. Keep future-version behavior behind explicit deferral notes rather than
    partial implementation.

## Module Coverage

| Feature document | Primary placement | Notes |
| --- | --- | --- |
| `core-model.md` | v0 | Foundational vocabulary for refs, records, manifests, filters, identifiers, timestamps, and hashing terminology. |
| `timestamps.md` | v0 | UTC helpers are needed by status, stores, provenance, logs, and generated IDs. |
| `protocols.md` | v0 | Tiny shared protocols and import-boundary rules come before subsystem contracts. |
| `errors.md` | v0, v1, v2, v3 | Shared roots land in v0; composition directive errors mature in v1; CLI formatting and local diagnostics mature in v2 and v3. |
| `serialization.md` | v0, v1 | Plain data and canonical JSON are prerequisites for fingerprints, stores, provenance, config snapshots, and composition manifests. |
| `fingerprints.md` | v0, v1 | Hash helpers and digest records underpin resume, artifact integrity, included-config provenance, copies, replacements, and source snapshots. |
| `io.md` | v0, v1, v14, v15, v16 | Local sources/codecs in v0; include URI resolution and source snapshots begin in v1; plugin source/codec loading in v14; remote hooks and operations in v15/v16. |
| `artifacts.md` | v0, v3, v9, v9-post, v10, v12, v15, v16, v21 | Local artifact refs/stores in v0; inspection in v3; commit/concurrency semantics in v9; authority-backed commit use is mandatory after v9; v10 adds durable service/offline import evidence; bundles/exporters in v12; external/remote interface, multi-location refs, and immutable reuse semantics in v15; payload materialization operations in v16; retention in v21. |
| `config.md` | v0, v1, v2, v13, v14, v23 | Composition, recipes, and instantiation in v0; includes, replacement, copy, and rebuildable manifests in v1; CLI exposure in v2; sweep overrides in v13; recipe plugins in v14; v23 compatibly extends queue controller and local-assignment configuration. |
| `pipeline.md` | v0, v2, v9, v13 | Static DAG specs, stage contracts, planning, and local execution belong to v0; CLI exposes them in v2; concurrent DAG lifecycle contracts land in v9; sweeps expose them later. |
| `pipeline-graph.md` | v0, v2, v3 | Pure graph construction, binding, traversal, and cycle checks precede execution and preflight. |
| `runtime-resources.md` | v4, v6, v7, v11, v17, v18, v23 | Shared runtime/resource objects arrive before executor-specific mapping; v11 adds queue pool reconciliation over authority resource leases; v23 adds concrete local assignment without changing portable resource requests. |
| `execution.md` | v0, v4, v5, v6, v7, v9, v9-post, v10, v11, v17, v18, v19, v23 | Local execution in v0; options in v4; subprocess in v5; SLURM and containers later; concurrency foundations in v9; v9-post removes local-only mutation entrypoints; v10 makes service connection/start policy explicit and durable; v11 adds whole-run queue dispatch; reliability in v19; v23 adds bounded concurrent managed-local process lifecycle. |
| `run-store.md` | v0, v3, v5, v8, v9, v9-post, v10, v11, v12, v19, v20, v21, v23 | Local layout in v0; inspection/failures/catalog build on it; v9 strengthens authoritative persistence contracts; v9-post deprecates `LocalRunStore` as a runtime entrypoint; v10 adds DB-backed authority service/offline import; v11 links queue and authority facts; v23 adds queue-owned local attempt logs and safe dispatch evidence; bundles/reliability/events/cleanup build on the shared contracts. |
| `state.md` | v0, v5, v7, v9, v9-post, v10, v11, v19, v23 | Basic statuses in v0; attempts/failures, scheduler state, concurrent lifecycle semantics, mandatory authority-backed lifecycle use, durable service state, queue status, and reliability records mature later; v23 adds explicit deferred dispatch and pool-cycle outcomes. |
| `provenance.md` | v0, v1, v6, v7, v10, v11, v14, v17, v18, v20 | Generic provenance in v0; config composition provenance in v1; submission, offline import evidence, queue dispatch facts, plugin, container, event, and event-sink facts added with those capabilities. |
| `resume.md` | v0, v2, v3, v9, v9-post, v10, v13, v19 | Same-run-directory resume in v0; CLI/preflight expose it; v9 clarifies interrupted attempts and leases; v9-post authority-backs continuation entrypoints; v10 adds offline import/equivalence policy; sweeps and retry policies build later. |
| `preflight.md` | v3, v4, v5, v6, v7, v9, v10, v11, v14, v15, v16, v17, v18, v19, v20, v21, v23 | Core check runner in v3; new checks arrive with each operational feature, including managed-local assignment consistency and capability checks in v23. |
| `run-catalog.md` | v8, v9, v9-post, v10, v12, v13, v15, v16, v21 | Catalog/comparison in v8; active-query guarantees and projections in v9; v9-post clarifies authority-backed behavior reads versus artifact-only local directory access; v10 service registry/offline import updates run visibility; bundles and exporters in v12; sweeps integrate in v13; metadata-only external/remote refs and immutable lookup in v15; explicit payload materialization in v16; cleanup later. |
| `sweeps.md` | v9, v9-post, v10, v11, v13 | V9 defines coordination primitives for large sweeps; v9-post shapes workspace authority and service-backed coordination; v10 service-backs workspace coordination; v11 provides whole-run queue dispatch that later sweeps can use; v13 implements deterministic sweeps as many ordinary runs. |
| `slurm.md` | v6, v7, v9-post, v10, v11, v18 | Script/dry-run support first; live operations second; v9-post removes local-only submitted-state mutation; v10 clarifies allocation-scoped service supervision and connection policy; v11 adds delegated queue dispatch; container composition after both are stable. |
| `container-executors.md` | v17, v18 | Docker first; Apptainer and SLURM-container composition second. |
| `remote-stores.md` | v9, v9-post, v10, v15, v16 | V9 shapes backend capability expectations; v9-post plans service/database authority for multi-host state; v10 delivers durable service supervision; external/remote interface contract, fake handlers, multi-location refs, and bundle ref semantics first; payload operations and optional real backends second. |
| `reliability.md` | v5, v9, v9-post, v10, v11, v19, v20, v21, v23 | Baseline failure metadata starts with subprocess; v9 defines concurrency/attempt foundations; v9-post makes those foundations mandatory across entrypoints; v10 adds service durability and offline import rejection/acceptance evidence; v11 requires accurate queue cancellation/status reporting; retry and timeout land in v19, events in v20, cleanup in v21, and v23 adds lease-renewal and exact resource-release safety for managed-local work. |
| `plugins.md` | v14, v15, v16, v20 | Explicit discovery in v14; remote backend, exporter, and event sink integration later. |
| `queue.md` | v11, v23 | V11 establishes the durable whole-run queue and local/SLURM adapters; v23 adds safe pool cycles, static concrete assignment, deterministic local logs, and redacted pool summaries. |
| `cli.md` | v2, v3, v5, v6, v7, v8, v9-post, v10, v11, v12, v13, v14, v16, v17, v18, v19, v20, v21, v23 | Core CLI lands in v2; commands grow only with their owning feature; v9-post authority-backs remaining mutating runtime commands; v10 adds service lifecycle/configuration and offline import commands; v11 adds queue operations; v23 extends queue status without placing scheduling logic in the CLI. |
| `testing.md` | all versions | Unit, contract, fake-backend, e2e, and opt-in integration suites should grow each version. |
| `examples/` and `*-example-coverage.md` | v22 | Cross-roadmap example inventory, runnable/manual status, validation tiers, integration/e2e behavior, and documentation refinement are consolidated after the runtime surface through v21 exists. |

## Functionality Not Encompassed By This Roadmap

The feature documents mention or leave room for the following capabilities, but
this roadmap does not assign them to a version. They should remain out of scope
until there is a specific downstream need and a separate design review.

- Domain-specific stages, codecs, artifact schemas, datasets, models, metrics,
  metric extractors, reports, analysis logic, recipes, or comparison semantics.
- Untrusted config sandboxing, import allow lists, plugin sandboxing, or
  treating containers as a security boundary.
- Hydra-compatible defaults, arbitrary config expression languages, advanced
  list patching, broad registry aliases for every component, and automatic
  schema inference for arbitrary targets.
- Runtime DAG mutation, conditional branch expression languages, nested task
  scheduling, dynamic fan-out/fan-in at execution time, and general distributed
  workflow-engine behavior.
- Automatic cross-run cache reuse as a default behavior, global
  content-addressed cache, partial stage reuse, and domain-specific checkpoint
  continuation in core `loom`. Explicit lookup and publication of
  project-declared immutable artifacts is scoped to v15/v16 instead.
- Hosted workflow orchestration, remote tracking servers, web dashboards,
  authorization systems, and hosted run catalog services as core Loom features.
  V10 owns database-backed authoritative service supervision for Loom's own
  persistence contract, but external systems such as Prefect or
  MLflow remain optional adapters.
- SLURM job arrays, multi-node MPI orchestration, cloud batch backends,
  Kubernetes, cluster-native controllers beyond v11 delegated dispatch, and
  workflow submission across unrelated clusters.
- Built-in Bayesian optimization, random search as a core feature,
  population-based training, adaptive trial generation, early stopping across
  trials, and metric query languages.
- Broad first-party parity across S3, GCS, Azure, MLflow, DVC, fsspec, and
  similar backends. v16 should select at most one optional adapter family if a
  concrete need exists.
- Full SBOM generation, cryptographic attestation, signed artifact manifests,
  distributed tracing, and remote telemetry.
- Service-specific notification delivery such as Slack, email, Teams,
  PagerDuty, or webhooks in core `loom`.
- Automatic artifact deletion, automatic run garbage collection, and aggressive
  cleanup policies without explicit user intent.
- Large real-data acceptance suites, real cluster tests, cloud-service tests,
  container-runtime tests, or network tests in the default test suite.

## Roadmap Review Triggers

Revisit this roadmap when any of the following become true:

- v0 acceptance tests expose a missing boundary that blocks CLI or subprocess
  work.
- A detailed project plan for any version violates the sizing rules above.
- A downstream project needs remote stores, plugins, or sweeps earlier than the
  current ordering.
- Users need a primitives-only install after config dependencies become hard
  runtime dependencies.
- The local run layout changes in a way that would affect catalogs, export,
  SLURM workers, containers, or remote stores.
- Concurrent stage execution, large sweeps, shared filesystems, or remote
  stores require stronger run-state guarantees than the current local
  filesystem backend can safely provide.
- Multiple downstream packages implement similar plugins, codecs, stores, or
  executor adapters outside `loom`.
- Operational failures show that reliability policy work should move earlier.
- External integration pressure repeats around the same adapter category, such
  as MLflow sinks/exporters, Prefect orchestration, DVC-backed artifacts, or
  Hydra config bridges.
- Standalone config usage needs independent release cadence beyond the
  external `weave` dependency.
