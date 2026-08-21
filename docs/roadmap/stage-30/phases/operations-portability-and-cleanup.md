# Phase 1 Execution Plan: Operations Portability And Cleanup

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 30, Phase 1
- Manifest: `docs/roadmap/stage-30/implementation-plan.md`
- Branch: `agent/stage-30-p1-operations-portability-and-cleanup`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; `/home/can134/work/active/loom-worktrees/stage-30-p1-operations-portability-and-cleanup`
- Base revision: `e3968f7`
- PR target: develop
- PR title: `Stage 30 phase 1: add run portability and cleanup journeys`
- Dependencies: Stage 8 run catalog, Stage 12 bundles, Stage 21 cleanup/GC, Stage 22 example harness, and Stage 26 operational guidance are merged.
- Workflow path: fast
- Blockers: none

## Objective And Context

- Vertical outcome: users can run one project that creates and compares two
  runs and transfers one through a bundle, plus a separate project that proves
  preview-first, candidate-only cleanup and GC.
- Earlier dependency: existing public CLI behavior and example manifest/test
  conventions.
- Later work explicitly out of scope: sweeps, event sinks, Apptainer, resume
  refinement, storage example, broad docs summaries, and all runtime changes.

## Current Source And Harness

- Relevant files and symbols: `examples/README.md`,
  `examples/operations/README.md`, `examples/support.py`, `loom runs` handlers,
  `loom clean`, `loom gc`, `PipelineRunner`, local authority/store helpers, and
  Stage 22 manifest checks.
- Existing tests and seams: `tests/e2e/test_cli_runs_e2e.py`,
  `tests/e2e/test_cleanup_cli.py`,
  `tests/integration/examples/test_example_workflows.py`, and
  `tests/integration/docs/test_v0_python_examples.py`.
- Import, dependency, or harness constraints: project stage modules must be
  importable in subprocess/CLI paths; examples must honor output-root variables;
  cleanup fixture setup may use a private repository seam but must be isolated
  and must not be described as a supported user API.

## Scope

In scope:

- Add `examples/operations/run-catalog-and-bundles/README.md`, `example.yaml`,
  `pipeline.yaml`, `stages.py`, and `run_catalog_workflow.py`.
- Create two ordinary successful runs with a stable meaningful difference.
- Execute index, list, diff, export-with-payloads, inspect, and import via actual
  CLI entrypoints and print stable evidence.
- Verify imported artifact payload contents equal the original contents.
- Add `examples/operations/cleanup-and-gc/` with README, manifest, a runnable
  entrypoint, synthetic committed artifact, temporary registered payloads, and
  an explicitly named setup-only fixture if needed.
- Execute per-run preview/delete and collection preview/delete via actual CLI
  entrypoints; prove preview does not mutate, only candidates are deleted, and
  run directories/committed outputs remain.
- Route both examples from the operations/root catalogs and add focused
  integration/e2e evidence.

Out of scope:

- Runtime, schema, CLI, bundle, catalog, cleanup, authority, or store changes.
- Whole-run deletion, arbitrary path scanning, retention-policy expansion,
  remote cleanup, tracking servers, or network transfer.
- Teaching private fixture APIs as project code.

Assumptions:

- Existing JSON envelopes remain the stable assertion surface.
- A setup fixture may seed authority cleanup facts solely to reach the existing
  public cleanup commands; README guidance starts after Loom has registered
  candidates.
- Exact generated run names may vary, but counts, statuses, diff categories,
  artifact ids, and payload bytes are deterministic.

## Fixed Contracts And Private Discretion

- Observable behavior: two indexed runs; a non-empty comparison; successful
  payload-bearing bundle export/inspect/import; equal imported bytes; inert
  cleanup/GC previews; candidate-only explicit deletion; preserved run and
  committed artifact paths.
- Public or durable shapes: existing run CLI JSON envelopes, bundle format,
  authority cleanup candidate/report/result facts, and example manifest fields.
- Trust and failure boundaries: bundle import remains strict; cleanup operates
  only on authority candidates inside managed roots and requires explicit
  intent; fixture-created candidates cannot broaden deletion authority.
- Cross-phase contracts: add catalog rows and manifests in the same style later
  phases will reuse; avoid owning unrelated feature docs.
- Reproducibility and compatibility: no generated outputs are committed;
  scripts accept Loom example output variables and run cleanly from a fresh
  checkout.
- Private choices the executor may simplify: helper layout, UUID/run naming,
  summary key names, whether shared setup helpers live beside one example, and
  test factoring.

## Proportionality

- Existing seam reused: public CLI through `examples.support.run_cli_json`,
  existing PipelineRunner/local store paths, and existing example integration
  harness.
- Material additions and current justification: two example directories plus
  focused tests are the smallest complete user journeys.
- Optional hardening and future capability deferred: no exhaustive CLI option
  matrix, corrupt bundle cases, cleanup selector matrix, real authority service
  acceptance profile, or performance assertions.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Catalog contains exactly the two example runs | Run catalog CLI | Example setup and collection root | Misleading comparison/list result | Entrypoint integration assertion |
| Imported payload equals exported payload | Bundle exporter/importer | Archive and target collection boundary | Portability claim is false | Read original/imported artifact refs and compare bytes |
| Preview has no filesystem side effect | Cleanup planning | Public clean/gc command boundary | Destructive default | Before/after path assertions |
| Delete touches only selected registered candidates | Cleanup execution plus authority candidates | Fixture facts and managed-root validation | Data loss or false safety claim | Candidate removed; run and committed artifact preserved |
| Example inventory remains truthful | Stage 22 manifest harness | New manifests/catalog rows | Broken or overstated docs | Existing manifest/link tests |

## Implementation Slices

1. Add the run catalog/bundle example project, complete script, README commands,
   and manifest.
2. Add the cleanup/GC project with an isolated candidate setup fixture and
   explicit safety explanation.
3. Update operations/root catalog routing and owner documentation references.
4. Add focused integration/e2e assertions that execute both entrypoints and
   inspect their durable outputs.
5. Run targeted formatting, typing, and tests; update only implementation and
   completion fields in this phase plan.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required via final gate | Examples do not alter public imports | Existing package suite remains green |
| Unit | required where manifest helper checks apply | Example metadata validity | Existing inventory assertions accept both manifests |
| Contract | required via final gate | No public/durable behavior changes | Existing catalog/bundle/cleanup contracts remain green |
| Integration | required | Complete run portability and cleanup journeys | Execute scripts; assert summaries and files |
| E2E / opt-in | targeted existing plus new as appropriate | Actual public CLI orchestration | Runs and cleanup CLI paths execute, not mocked formatters |

Targeted commands:

    uv run pytest tests/integration/examples/test_example_workflows.py tests/integration/docs/test_v0_python_examples.py
    uv run pytest tests/e2e/test_cli_runs_e2e.py tests/e2e/test_cleanup_cli.py
    uv run ruff check examples tests/integration/examples

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: relying on private fixture behavior in the demonstrated path;
  asserting unstable generated ids; bundle payload comparison against the wrong
  run; GC discovering generated non-run directories.
- Review focus: README clearly separates fixture setup from public cleanup
  commands; scripts execute actual command handlers; all outputs stay beneath
  configured roots; no runtime behavior is changed.
- Stop if: public commands cannot complete the requested journey without a
  runtime/API/schema change, cleanup needs arbitrary path authority, or bundle
  import cannot preserve the example payload.
- Accepted debt and revisit trigger: cleanup setup is fixture-backed; revisit if
  a public producer-facing cleanup-candidate API is later accepted.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above, in order or combined when
  tests stay reviewable.
- Decisions not to revisit: examples/docs/tests only; two separate journeys;
  actual CLI execution; no runtime additions; fixture setup must be explicit and
  isolated.
- Conditions requiring manager action: any need to edit `src/loom`, change a
  durable format, weaken cleanup safety, or alter accepted phase scope.

## Workflow State

- Manager preparation: complete; planning and phase plan approved, fast-path
  quality review passed, and the worktree was created from `origin/develop` at
  `e3968f7` with unrelated control-checkout work excluded.
- Expanded planning: not needed.
- Implementation: pending.
- Refiner: not needed / pending evidence.
- Pre-submit gate: pending.
- Independent review: not needed / pending residual-risk check.
- Blocker corrections: 0/3
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
