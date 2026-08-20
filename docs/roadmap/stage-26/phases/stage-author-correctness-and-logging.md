# Phase 1 Execution Plan: Stage-Author Correctness And Lifecycle Guidance

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 26, Phase 1
- Manifest: `docs/roadmap/stage-26/implementation-plan.md`
- Branch: `agent/stage-26-p1-stage-author-correctness-and-logging`
- Worktree root and path: `../loom-worktrees`;
  `../loom-worktrees/stage-26-p1-stage-author-correctness-and-logging`
- Base revision: `3464d52` (`origin/develop`; Stage 25 remotely merged)
- PR target: `develop`
- PR title: `Stage 26 phase 1: clarify stage operations and lifecycle facts`
- Dependencies: Stage 25 remotely merged; planning `FR-1` through `FR-5`,
  `FQ-1` through `FQ-5`, and `DQ-1` through `DQ-4`
- Workflow path: fast unless the source audit demonstrates a new public or
  durable contract decision
- Blockers: none

## Objective And Context

- Vertical outcome: a downstream author can copy one small guide and examples
  to read inputs, write managed or file-backed outputs, use temporary workspace,
  return artifacts, emit or write logs deliberately, and inspect the correct
  logs for the chosen executor, while lifecycle documentation and preparation-
  failure observation match committed state.
- Earlier dependency: existing StageContext/store/executor/SLURM/queue behavior
  and Stage 24-25 lifecycle boundaries remain authoritative.
- Later work explicitly out of scope: Stage 28 event subscriptions and plugin
  activation; any notification abstraction or provider adapter; scheduler,
  resource-usage sampler, new resume policy, acceptance profile, or validation-
  gate change.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/pipeline/context.py::StageContext` already owns
    `input_artifact`, `load_input`, `load_artifact`, `local_output_path`,
    `local_workspace_path`, `save_artifact`, and `register_local_artifact`.
  - `src/loom/pipeline/executors/local.py::LocalExecutor` defaults to stream
    pass-through; optional capture redirects Python streams and is rejected for
    bounded parallel local execution.
  - subprocess, Docker, and Apptainer executors write child stdout/stderr to the
    stage request paths and preserve failure/result path evidence.
  - SLURM manifests may name scheduler wrapper stdout/stderr separately from
    Loom stage logs.
  - queue-managed attempts have queue-owned per-attempt logs, separate from a
    run's stage log path.
  - lifecycle emitters include `run.cancelled`, `stage.cancelled`, and
    `run.preparation_failed`; older event prose does not list all current names;
    and fresh-run preparation failure currently emits before committing
    `FAILED`, contrary to the existing post-commit event contract.
- Existing tests and seams:
  - context/artifact contracts validate output names, store availability, and
    `ArtifactRef` returns;
  - local/subprocess/container/SLURM fake-command tests cover stream path
    construction and failure evidence;
  - `examples/operations/captured-logs/` is the current runnable local capture
    and CLI inspection path; and
  - integration tests already verify event order and post-commit observation.
- Import, dependency, or harness constraints:
  - examples remain domain-neutral, dependency-free, deterministic, and safe
    for default local validation;
  - documentation may describe real runtimes but this phase adds no real
    container, cluster, GPU, service, or network requirement; and
  - do not add a structured-logging dependency, direct stage store handle, or
    new public path helper.

## Scope

In scope:

- Add `docs/downstream-operations.md` as the simple authoritative journey, with
  short runnable-style Python snippets and links to detailed feature specs.
- Explain managed-object output versus file-backed output:
  - `save_artifact()` serializes a value through a codec;
  - `local_output_path()` plus `register_local_artifact()` registers a file;
  - returned mappings still contain declared `ArtifactRef` values; and
  - `local_workspace_path()` is for intermediate/work files and does not make a
    file an output or artifact automatically.
- Explain input refs and loading, unavailable local helpers for non-local
  stores, output contract checks, and project ownership of domain schema and
  checkpoint compatibility.
- Add one compact logging table for local, subprocess, Docker, Apptainer,
  SLURM, and managed queue paths, covering:
  - what captures stdout/stderr and whether capture is optional;
  - where traceback, wrapper, stage, and queue-attempt logs differ;
  - how `loom logs` relates to stage streams;
  - that a project `FileHandler` writes where project code points it and is not
    automatically an artifact or `loom logs` stream; and
  - that preconfigured Python handlers may retain their original stream, while
    handlers configured inside a captured process/stage normally follow that
    process's streams. Avoid guarantees about native file-descriptor capture in
    the in-process local redirect path.
- Expand or add the smallest hermetic examples needed to demonstrate managed
  save, file registration/workspace, captured stdout/stderr, and a stage-owned
  file that becomes durable only when explicitly registered.
- Audit the exact implemented lifecycle event names, commit ordering, artifact
  path claims, log path claims, and public examples. Correct canonical docs and
  the smallest authoritative source/test issue only when a reachable mismatch
  is demonstrated.
- In `_record_preparation_failure`, commit `FAILED` before emitting
  `run.preparation_failed` for a fresh run. Preserve the current rule that an
  already-terminal opened run is not reset or rewritten.
- Update roadmap and feature-doc cross-references so scheduling, resource-usage
  observation, resume changes, notification extension mechanics, and new gate/
  profile work are assigned to their authoritative later stages or explicitly
  deferred.
- Add the guide to appropriate README/doc routing without making it a package
  import or generated artifact.

Out of scope:

- A logger object on `StageContext`, log schema, aggregation/streaming service,
  remote log API, automatic arbitrary-file discovery, log retention change, or
  cross-executor behavior normalization.
- Changing the direct returned-output contract, exposing stores, adding a
  remote writer API, or parsing project log/artifact contents.
- Rewriting completed historical phase plans solely to change their Stage 26
  wording. Update current canonical docs and active adjacent planning only
  where the cross-reference is material.
- Notification severity/message/notifier values, registration adapters,
  provider examples, event subscriptions, or plugin activation. Direct project
  event sinks remain existing behavior; Stage 28 owns new generic mechanics.
- New external acceptance suites, environment profiles, Make targets, or CI
  requirements.

Assumptions:

- The existing context facade and log path APIs can support accurate guidance.
- A documentation claim that cannot be proven from current source/tests is
  narrowed rather than implemented speculatively.
- Small compatibility fixes discovered by the audit remain in phase only when
  they restore already documented/current public behavior without a new public
  or durable design.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - stage examples return declared `ArtifactRef` mappings;
  - workspace files are never described as automatic outputs;
  - executor stream behavior and file locations are labeled by owner;
  - `loom logs` examples identify stage streams and do not imply it reads every
    project file or SLURM wrapper log; and
  - lifecycle-event documentation matches emitted names and states that the
    corresponding committed fact precedes observation; and
  - fresh-run preparation failure persists `FAILED` before observers run,
    while an already-terminal opened run retains its terminal state.
- Public or durable shapes: none added. Existing context, artifact, log,
  event, failure, queue, SLURM manifest, and store formats remain authoritative.
- Trust and failure boundaries:
  - project code owns its logging configuration, file paths, domain schemas,
    and checkpoint compatibility;
  - Loom owns only paths/capture/evidence it explicitly creates; and
  - docs do not treat stdout/stderr, workspace files, or log contents as
    audience-safe notification payloads.
- Cross-stage contracts: this phase settles the event catalog and committed-
  fact language consumed by Stage 28. It does not define notification message
  selection, severity, subscriptions, or activation.
- Reproducibility and compatibility: examples use temporary/unique run roots,
  no network, and supported public imports. Existing executor defaults do not
  change merely to make a table uniform.
- Private choices the executor may simplify: exact guide section order,
  whether the file-backed snippet extends an existing example or uses one new
  small example, helper/test names, and wording that preserves the fixed
  distinctions.

## Proportionality

- Existing seam reused: StageContext, artifact codecs/register, local workspace,
  executor request log paths, `loom logs`, SLURM manifests, queue attempt facts,
  lifecycle event tests, and the example harness.
- Material additions and current justification: one guide and a small example
  close demonstrated user-facing gaps; the event/source correction prevents
  observers from seeing a fact that contradicts authoritative state.
- Optional hardening and future capability deferred: logging facade, structured
  log events, log shipping, remote path abstraction, docs generation, full
  executor matrix, and environment-dependent acceptance.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Outputs are explicit refs | `StageContext`/runner output validation | copied downstream stage example | untracked file or false successful output | context contract and runnable example |
| Workspace is not artifact publication | StageContext/artifact store boundary | guide/example | resume/export assumes an unregistered file | exact example/output assertions |
| Stream paths are owner-specific | executor/store/SLURM/queue | unified prose | operator inspects the wrong path | logging table review plus focused tests |
| Local capture limits are truthful | local executor/runner admission | docs imply process-level or parallel-safe capture | missing/misattributed logs | local capture/pass-through and parallel rejection tests |
| Lifecycle catalog matches source | runner/lifecycle/events | stale feature prose | observers and operators misclassify outcomes | exact emitted-name audit/integration sequence |
| Preparation failure is post-commit | runner preparation-failure path | fresh-run ordering | observer sees stale `CREATED` state | callback reads `FAILED`; terminal open-existing regression |
| Domain content remains downstream | project code | convenience example names/types | Loom gains domain schema/log semantics | docs and import review |

## Implementation Slices

1. Inventory the exact current stage-context, output, stream, traceback, queue,
   SLURM-wrapper, CLI-log, and lifecycle-event behaviors; record only reachable
   mismatches.
2. Add the downstream operations guide with the managed-save, file-register,
   workspace, input, logging, and inspection snippets.
3. Strengthen the smallest existing examples/tests for file-backed output and
   logging distinctions; keep them dependency-free.
4. Correct demonstrated source/docs/tests at the authoritative owner, including
   fresh-run preparation-failure ordering, without adding public machinery.
5. Update README/feature/roadmap routing and run targeted validation followed by
   the final phase gates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required if imports/routing change | public API remains unchanged | no unintended exports or heavyweight imports |
| Unit | required for any source correction | helper/executor truth | only the behavior touched by a demonstrated mismatch |
| Contract | required | stage output/context/log contracts | declared refs, explicit registration, existing stream/path surfaces |
| Integration | required | runner/executor/event coordination | captured/pass-through logs, exact event names, and fresh preparation failure observed after `FAILED` |
| E2E / opt-in | one hermetic example required; external deferred | copyable downstream journey | unique run, artifact contents/refs, stream inspection, no network/runtime dependency |

Targeted commands:

    uv run pytest -q tests/contracts/test_stage_contract.py tests/unit/loom/pipeline/test_context.py
    uv run pytest -q tests/integration/pipeline/test_local_execution.py tests/integration/diagnostics/test_cli_status_logs.py
    uv run pytest -q tests/unit/loom/pipeline/execution/test_runner.py
    uv run pytest -q tests/integration/examples/test_example_workflows.py tests/unit/loom/cli/test_status_logs.py

The executor should adjust exact paths to current test ownership rather than
creating placeholder test modules.

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: turning documentation cleanup into feature work, describing local
  redirection as OS-level capture, conflating wrapper/stage/queue logs,
  implying workspace persistence equals artifact publication, or editing
  unrelated Stage 27-29 planning.
- Review focus: every high-level claim has one source/test owner; snippets use
  supported public imports; no accidental API/schema/gate change; roadmap
  deferrals are consistent.
- Stop if:
  - accurate guidance requires a new public log/artifact API;
  - a proposed correction changes durable formats or accepted executor
    behavior rather than fixing a demonstrated mismatch;
  - examples require an external runtime/service; or
  - current user changes in roadmap/Stage 27-29 cannot be preserved safely.
- Accepted debt and revisit trigger: executor logging remains intentionally
  heterogeneous. Revisit only after a demonstrated user workflow requires one
  additional generic owner, not for documentation symmetry.

## Executor Handoff

- Read section range: this plan plus planning `FR-1` through `FR-5`,
  `Functionality Agreement`, `Minimum Design`, and `Phase Shaping`.
- Safe implementation slices: the five numbered slices; inventory before edits
  and prefer documentation/example corrections over source changes.
- Decisions not to revisit: no new public surface, logger, remote writer, gate,
  profile, scheduler, sampler, resume semantics, or notification feature in
  this phase.
- Conditions requiring manager action: any stop condition, event-name/commit
  ambiguity that changes Stage 28's observer boundary, or overlapping user
  changes that cannot be preserved.

## Workflow State

- Manager preparation: complete; Stage 25 merge, source seams, exact targeted
  test paths, branch, worktree, base, target, and title verified
- Expanded planning: not needed unless a stop condition is reached
- Implementation: pending one `loom_phase_executor` from prepared revision
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: manager-local fast path
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
