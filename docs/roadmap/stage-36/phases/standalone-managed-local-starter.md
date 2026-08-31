# Phase 1 Execution Plan: Standalone Managed-Local Starter

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 36, Phase 1
- Manifest: docs/roadmap/stage-36/implementation-plan.md
- Branch: agent/stage-36-p1-standalone-managed-local-starter
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-36-p1-standalone-managed-local-starter`
- Base revision: `95e45a3a65d485b7e0d335177371986a845c1120`
- PR target: develop
- PR title: `Stage 36 phase 1: add standalone managed-local starter`
- Dependencies: merged Stage 29 managed service and Stage 34 run inspection
- Workflow path: fast; the approved additive facade composes existing owners
  and introduces no schema or unresolved trust decision
- Blockers: none

## Objective And Context

- Vertical outcome: a copied project directory prepares and completes one
  dependency-ordered run through `daemon-init`/`daemon-serve`, observes it,
  verifies its output, and reopens the same durable service state after restart.
- Earlier dependency: Stages 29 and 34 own all daemon, authority, execution,
  management, inspection, restart, and process-cleanup behavior.
- Later work explicitly out of scope: remote agents, ready-stage SLURM,
  preparation repair/delete, content transfer, and service-manager packaging.

## Current Source And Harness

- Relevant files and symbols: `prepare_managed_local_runtime_record`, strict
  runtime loader, coordinator deployment loader/config, `LocalRunStore`,
  `PipelineSpec`, `plan_pipeline`, runtime config/metadata helpers, embedded
  authority initializer/opener, lazy queue exports, and `managed-local-basic`.
- Existing tests and seams: queue package import tests, deployment/runtime unit
  tests, local daemon production integration, queue CLI E2E journey and manifest
  parity, documentation catalog checks, and process-tree cleanup helpers.
- Import, dependency, or harness constraints: public queue imports stay lazy;
  the copied example imports no repository helper/test module; default tests
  require no network, TLS, GPU, SLURM, or process manager.

## Scope

In scope:

- Add a frozen typed preparation receipt and lazy public preparation function
  accepting protected coordinator config, authored pipeline config, and safe
  one-segment run name.
- Validate embedded-only composition and root/runtime agreement before writes;
  derive requirements from the embedded protected descriptor.
- Compose/validate config and pipeline, persist existing config/provenance,
  plan/runtime/exact record state, and initialize embedded authority.
- Implement read-only exact replay and fail-closed existing partial/changed/
  corrupt state without repair or overwrite.
- Replace `managed-local-basic` inline/in-process/shared-helper wiring with
  self-contained stages, pipeline, protected config template/setup,
  preparation script, and real role/CLI lifecycle runner.
- Update feature/example docs, catalog claims, stale schema wording and Stage 29
  planning header, plus focused/package/copied E2E validation.

Out of scope:

- Runtime-record schema changes, alternate authority kinds, remote/SLURM
  requirement selection, overlays/CLI overrides, plugin activation, queue
  submission within preparation, artifact byte service, state repair/forget,
  TLS, daemonization framework, or domain stages.

Assumptions:

- Weave composition and current public pipeline models are installed with Loom.
- The basic example's current Python environment contains the installed Loom
  CLI/package and is a valid resident worker executable.
- Exact replay occurs after a complete prior call; a concurrent observer of an
  in-progress first call may receive the deliberate partial-state conflict.

## Fixed Contracts And Private Discretion

- Observable behavior: fresh prepare returns a receipt; exact complete replay
  returns equal receipt without freshness/file mutation; any mismatch or
  incomplete existing run fails; preparation never starts or submits work.
- Public or durable shapes: function name/signature and frozen receipt fields
  are public; no new durable shape is added and existing schemas remain exact.
- Trust and failure boundaries: protected service config supplies paths/code
  identity; authored pipeline config is trusted project code; unsupported
  advanced composition is rejected before run creation; authority/runtime
  corruption remains explicit.
- Cross-phase contracts: none; the same phase adds the only current consumer
  and its validation.
- Reproducibility and compatibility: resolved/redacted/config composition
  evidence, runtime options, plan, and exact execution intent agree; existing
  lower API behavior and advanced examples remain compatible.
- Private choices the executor may simplify: module-private helper layout,
  receipt digest calculation reuse, exact safe run-name character validation,
  example subprocess helper structure, and text output beyond named facts.

## Proportionality

- Existing seam reused: deployment/config loaders, Weave, public pipeline/store
  APIs, runtime metadata, exact runtime writer/loader, authority owner, all CLI
  commands, Stage 34 projection, and current example manifest harness.
- Material additions and current justification: one facade owns otherwise
  duplicated cross-owner ordering/identity/replay; a self-contained example is
  the accepted downstream consumer and portability proof.
- Optional hardening and future capability deferred: automatic partial repair,
  cleanup, arbitrary run URIs, advanced target selection, process-manager
  installers, and content relay.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Run root and execution identity come from one config | preparation facade over deployment config | caller-authored runtime or repeated strings | daemon cannot place the prepared work | root conflict unit and copied execution E2E |
| Executable intent stays exact | existing runtime record writer/loader | summary/changed plan/config | wrong code/options execute | digest/file assertions and conflict tests |
| Replay never mutates | preparation facade comparison | response-loss retry | changed freshness/evidence or overwritten run | before/after stat/freshness plus equal receipt |
| Unsupported advanced owners fail before writes | facade validation | remote/TLS/SLURM config | false support or wrong target | one test per owner family and absent run directory |
| Copied project has no repository coupling | example directory | shared helper or relative checkout path | downstream copy fails | randomized copied-directory subprocess E2E |
| Service restart preserves owner identity and cleans processes | existing daemon/supervisor | real foreground service stop/restart | lost admission or leaked worker | same E2E stable ID, rotated epoch, terminal admission, dead PIDs |

## Implementation Slices

1. Add the typed receipt, embedded-only validation, fresh preparation and exact
   replay using existing owners; expose lazily and cover public/failure behavior.
2. Split the basic example into authored pipeline/stages, protected config
   template/setup and thin preparation entrypoint with direct artifact output.
3. Rework its lifecycle runner and E2E around copied files and real
   `daemon-init`/`daemon-serve`, including inspection, replay, restart, and PID
   cleanup.
4. Update README/catalog/feature wording and documentation assertions.
5. Run focused checks, full validation, summary, and manager diff review.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public API remains intentional and cheap | lazy receipt/function imports and build |
| Unit | required | Input, composition, persistence, replay/conflict | local-only rejections, exact facts, zero-write replay |
| Contract | deferred | No new implementable protocol | public concrete helper only |
| Integration | required if unit fakes cannot prove owner open | Config/plan/runtime/authority composition | real temp run and embedded authority |
| E2E | required | Copy portability and process lifecycle | real init/serve/submit/wait/inspect/artifact/restart/no PIDs |

Targeted commands:

    uv run --extra config pytest tests/unit/loom/queue tests/package/test_queue_api.py
    uv run --extra config pytest tests/e2e/test_queue_cli.py -k managed_local_basic
    uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: preparation duplicates ordinary config persistence incorrectly,
  exact replay mutates timestamps, helper silently supports advanced routes, or
  the E2E still succeeds only because of repository imports/paths.
- Review focus: one owner for roots/fingerprints, comparison-before-write,
  exact existing schemas, public import weight, copied working directory, real
  service process, and cleanup.
- Stop if: complete replay requires a new durable transaction/schema; current
  public APIs cannot preserve composed evidence; local-only validation cannot be
  established before writes; or the copied worker needs an internal import.
- Accepted debt and revisit trigger: no partial repair or automatic state
  deletion; revisit only after a concrete operational failure or managed
  retention requirement.

## Executor Handoff

- Read section range: this entire phase plan; Stage 36 planning Minimum Design,
  FR-1 through FR-8, DQ-1 through DQ-4; `docs/structure.md` queue/pipeline import
  direction; current managed-local example and exact runtime preparation source.
- Safe implementation slices: facade/replay; public tests; example project;
  copied service E2E; docs and focused/full gates.
- Decisions not to revisit: embedded-only, safe run name under service root,
  exact no-write replay, no repair/schema, actual daemon commands, no shared
  example helper.
- Conditions requiring manager action: any stop condition, public signature or
  durable format change, advanced-route support, dependency addition, or
  inability to prove copied portability.

## Workflow State

- Manager preparation: complete; approved planning packet `95e45a3`, current
  `origin/develop`, dedicated branch/worktree, source seams, fast-path route,
  and exact executor boundary verified.
- Expanded planning: not needed; fast path approved.
- Implementation: complete; added the lazy embedded-only preparation facade,
  immutable replay comparison, self-contained copied starter, documentation,
  and phase-scoped coverage.
- Refiner: not needed unless a qualified blocker appears.
- Pre-submit gate: pending.
- Independent review: not needed on the fast path unless material residual risk
  appears.
- Blocker corrections: 0/3.
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `src/loom/queue/managed_local_preparation.py`, lazy queue export, `managed-local-basic` self-contained pipeline/stages/lifecycle/config setup, catalog/feature/Stage 29 wording, and focused package/unit/E2E coverage. |
| Tests added or updated | New facade unit coverage; queue public-import assertion; copied `managed-local-basic` real `daemon-init`/`daemon-serve` E2E; catalog expectations updated. |
| Validated revision/tree state and evidence | `make validate-pr` passed (ruff, pyright, default/config-extra tests, build); `make test-summary` passed at 2026-08-31T06:35:51Z (2,933 passed; 3 expected skips). Focused facade/public/copy E2E pass: 6 passed. |
| Validation-relevant changes after evidence | None; this completion-record update is workflow metadata only. |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
