# Phase 2 Execution Plan: Experiments, Observers, And Apptainer

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 30, Phase 2
- Manifest: `docs/roadmap/stage-30/implementation-plan.md`
- Branch: `agent/stage-30-p2-experiments-observers-and-apptainer`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; `/home/can134/work/active/loom-worktrees/stage-30-p2-experiments-observers-and-apptainer`
- Base revision: `4513da7`
- PR target: develop
- PR title: `Stage 30 phase 2: demonstrate sweeps observers and Apptainer`
- Dependencies: Stage 30 Phase 1 remote merge and existing Stage 13/18/20/22 behavior.
- Workflow path: fast
- Blockers: none

## Objective And Context

- Vertical outcome: three focused projects let users run a deterministic
  two-trial experiment, consume committed lifecycle facts with isolated
  observers, and exercise the Apptainer executor without a real HPC runtime.
- Earlier dependency: Phase 1 establishes Stage 30 catalog/test conventions.
- Later work explicitly out of scope: resume, artifact materialization, final
  feature-doc summaries, filters, notifications, providers, and runtime changes.

## Current Source And Harness

- Relevant files and symbols: `loom sweep` handlers, `EventSinkRegistry`,
  `RunRequest.event_sink_registry`, event failure facts, Apptainer/Singularity
  executors and preflight, Docker fake-command example, root/execution catalogs.
- Existing tests and seams: sweep CLI e2e tests, local execution event-sink
  integration tests, Apptainer fake-runner integration tests, Docker example e2e
  journey, and Stage 22 example inventory/smoke harness.
- Import, dependency, or harness constraints: project-local stage modules must
  be importable in sweep/container worker processes; fake Apptainer must execute
  the worker command locally and log only safe/redacted command evidence.

## Scope

In scope:

- Create `examples/experiments/deterministic-sweep/` with README, manifest,
  `sweep.json`, pipeline, stages, and `run_sweep.py`.
- Add root/experiments catalog routing and run plan/run/status/collect through
  the actual CLI for exactly two manual trials.
- Create `examples/extensions/event-sink/` with README, manifest, pipeline,
  stages, and Python entrypoint using direct `EventSinkRegistry` registration.
- Observe `run.started`, stage completion, and `run.completed`; include one
  failing observer and prove run success plus recorded failure evidence.
- Document plugin entry-point packaging as a secondary snippet, not the primary
  path.
- Create `examples/execution/containers/slurm-apptainer/` with README, manifest,
  pipeline, stages, fake executable helper, and public CLI entrypoint.
- Prove `apptainer exec --cleanenv --nv ...` and successful artifacts without a
  real runtime; document optional live preflight/run and SLURM composition.
- Route all examples and add focused integration/e2e evidence.

Out of scope:

- Sweep optimizers, metric extraction semantics, parallel scheduling, queue
  expansion, event filters/retries/templates, service-specific sinks, real
  plugin package installation, container builds, real scheduler/container
  execution in default CI, and runtime source changes.

Assumptions:

- Sweep collection counts artifact refs produced by the two normal trial runs.
- Event callbacks receive committed `PipelineEventRecord` values on this local
  runner path and observer exceptions remain best effort.
- Fake Apptainer mirrors the established fake Docker approach and proves Loom's
  command integration, not container isolation.

## Fixed Contracts And Private Discretion

- Observable behavior: two planned/succeeded/collected trials; successful run
  with required observed events and one failure record; fake Apptainer call with
  `exec`, `--cleanenv`, `--nv`, selected image, and worker command.
- Public or durable shapes: sweep JSON/manifests, CLI envelopes, event records,
  failure facts, runtime profile adapter options, example manifests.
- Trust and failure boundaries: sweep config is trusted project code; sinks are
  observe-only and isolated; fake runtime is test infrastructure and live
  prerequisites are explicit.
- Cross-phase contracts: follow Phase 1 catalog/summary conventions and leave
  final feature-doc restructuring to Phase 3.
- Reproducibility and compatibility: fixed two-trial manual spec, local/fake
  roots, no network, no generated committed output, safe command logging.
- Private choices the executor may simplify: exact stage payloads, fake command
  helper factoring, event summary format, and whether tests share runner helpers.

## Proportionality

- Existing seam reused: sweep CLI, instance-local registry, Docker fake-command
  example, example inventory and integration harness.
- Material additions and current justification: three directories are needed
  because their prerequisites and failure models differ.
- Optional hardening and future capability deferred: full sweep failure matrix,
  observer link examples, installed wheel/plugin acceptance, Singularity alias
  journey, and live HPC tests.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Sweep expands and completes exactly two trials | Sweep planner/runner | Authored spec and trial override boundary | Deterministic collection claim false | Entrypoint summary and manifests |
| Sink failures do not fail the pipeline | Event dispatcher | Callback exception boundary | Observer becomes runtime authority | Successful RunResult plus failure fact assertion |
| Sinks observe committed lifecycle facts | Runner event emission | Event ordering boundary | Audit guidance misleading | Required event names and records |
| Apptainer command contains selected flags/image | Apptainer command builder | Runtime options to process argv | Example does not prove HPC path | Fake command log assertion |
| Fake validation is not described as live validation | Example docs | External-system boundary | Capability overclaim | README/manual prerequisite review |

## Implementation Slices

1. Add the deterministic sweep group/project, routing, and full lifecycle test.
2. Add the direct event-sink project, failure-isolation proof, packaging snippet,
   routing, and integration test.
3. Add the Apptainer project by adapting the fake Docker strategy, plus optional
   live/SLURM guidance and e2e evidence.
4. Run inventory/smoke tests and update phase completion fields.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required via final gate | Existing imports remain cheap | Existing suite |
| Unit | required via final gate | Existing event/Apptainer contracts remain | Existing suite; no new matrix |
| Contract | required via final gate | No public shapes change | Existing contracts |
| Integration | required | Sweep and event sink complete journeys | Entrypoints, durable facts, artifact counts |
| E2E / opt-in | required for Apptainer | Actual CLI/process command path | Fake executable log and successful run |

Targeted commands:

    uv run pytest tests/e2e/test_sweep_cli.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_apptainer_executor.py
    uv run pytest tests/integration/examples/test_example_workflows.py tests/e2e/test_example_journeys.py tests/integration/docs/test_v0_python_examples.py
    uv run ruff check examples tests/integration/examples tests/e2e/test_example_journeys.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: trial override expressions target nonexistent config paths; sweep
  outputs land outside configured roots; event example reads transient callback
  state but not durable failure evidence; fake Apptainer fails to forward worker
  environment/argv; docs imply fake coverage proves a live system.
- Review focus: actual CLI/API use, event ordering and failure isolation,
  hermetic process behavior, clear fake/live distinction, and domain neutrality.
- Stop if: acceptance needs runtime edits, service-specific behavior, provider
  dependencies, or an unbounded retry/filter/sweep policy.
- Accepted debt and revisit trigger: plugin entry-point packaging and live HPC
  remain documentation-only until a concrete distributable/live fixture exists.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the four slices above.
- Decisions not to revisit: three focused examples; direct registry primary;
  fake Apptainer default; no runtime additions.
- Conditions requiring manager action: runtime/public/durable changes, external
  dependency, or inability to prove observer isolation through existing facts.

## Workflow State

- Manager preparation: passed on `4513da7`; Phase 1 is remotely merged and its
  completion metadata is current on `origin/develop`.
- Expanded planning: not needed.
- Implementation: passed; added deterministic sweep, direct event-sink, and
  fake-Apptainer examples with focused catalog and journey coverage.
- Refiner: not needed / pending evidence.
- Pre-submit gate: pending.
- Independent review: not needed / pending residual-risk check.
- Blocker corrections: 0/3
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `examples/experiments/deterministic-sweep/`, `examples/extensions/event-sink/`, and `examples/execution/containers/slurm-apptainer/`; routed their group/root catalogs and added focused example tests. |
| Tests added or updated | Added sweep and event-sink integration journeys, fake-Apptainer e2e coverage, and v30 catalog assertions. |
| Validated revision/tree state and evidence | Executor tree: focused examples/catalog suite 6 passed; sweep/Apptainer regression suite 3 passed; local execution suite 9 passed; `ruff check` passed. |
| Validation-relevant changes after evidence | None. |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
