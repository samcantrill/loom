# Phase 3 Execution Plan: Operator Status And End-To-End Proof

## Metadata

- Status: pending
- Roadmap stage and phase: v23 Phase 3
- Manifest: `docs/roadmap/stage-23/implementation-plan.md`
- Branch: `agent/stage-23-p3-operator-status-proof`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-23-p3-operator-status-proof`
- Base revision: current `origin/develop` after Phase 2 merges; record the exact
  revision before branch creation
- PR target: `develop`
- PR title: `Managed Local Concurrency - Phase 3: Operator Status and Proof`
- Dependencies: Phases 1 and 2 remotely merged with their cycle, evidence,
  config, ownership, and local lifecycle contracts intact
- Workflow path: expanded because status serialization/redaction, CLI envelope
  compatibility, and causal concurrency end-to-end evidence have durable impact
- Blockers: Phase 2 must merge before this phase is selected

## Objective And Context

- Vertical outcome: Python and CLI callers can inspect one selected pool's
  queued/active/terminal counts and safe active assignment/process/log facts,
  and a dependency-free example proves bounded concurrency and refill.
- Earlier dependency: Phase 1 supplies safe cycle/base local evidence; Phase 2
  supplies schema-tagged assignment/log evidence and the managed-local path.
- Later work explicitly out of scope: managed worker command, log following,
  bulk submission CLI, dynamic resource observation, vendor acceptance in
  default checks, generic scheduling, notifications, and process reattachment.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/repository.py`, `_sqlite.py`, and `service.py`: recovery-only
    reads and no general pool/queue/status list/count surface.
  - `src/loom/queue/status.py`: `QueueOperationalStatus`, broad active-item
    serialization, optional live adapter inspection, and ownership wording.
  - `src/loom/cli/queue.py` and `src/loom/cli/formatting.py`: queue status
    command, v1 JSON envelope, and text formatting.
  - `examples/operations/`, `examples/README.md`, and the example metadata
    conventions established by v22.
  - `docs/features/queue.md`, `runtime-resources.md`, `run-store.md`,
    `preflight.md`, `reliability.md`, `cli.md`, and `testing.md`.
- Existing tests and seams: queue CLI contract/integration/e2e tests, queue
  repository tests, status/formatting tests, example inventory checks, and
  Phase 2's fake/real SQLite coordination harness.
- Import, dependency, or harness constraints: the read model owns redaction;
  CLI renders only that model. Default examples use generic slot labels, short
  local subprocesses, temporary state, and no accelerator or network.

## Scope

In scope:

- One repository/service pool-summary read for a selected pool, with status
  counts and deterministically ordered active rows from one SQLite read
  snapshot. Query grouping and reusable internal filters remain private.
- One pool-status read model with explicit fields for pool name, configured
  single-controller active limit, queued, claimed/dispatched active, succeeded,
  failed, cancelled, and unknown counts, plus allowlisted active-attempt rows.
- Active rows containing queue item ID, persisted safe slot IDs/labels,
  PID/PGID, queue-relative stdout/stderr paths, owner/session, and a clear
  `persisted` versus same-session `live` evidence source. Claimed work without a
  handle has no fabricated assignment.
- `loom queue status CONFIG --pool POOL` over the existing Python status builder;
  text and JSON come from the same model. Existing service-level and `--item`
  status remain available. Advance the existing queue-status envelope to v2 if
  the additive model cannot retain v1's exact documented shape.
- Redaction that never emits raw `DispatchHandle.evidence`, fencing tokens,
  command/cwd, environment names/values, provider-private payloads, or unknown
  legacy evidence keys in the new pool summary.
- A dependency-free managed-local operations example with two generic static
  slots and at least three short argv commands, distinct logs, and status
  inspection.
- Required real-SQLite scenario with twelve items over three static slots,
  including replacement after success, non-zero exit, and cancellation; peak
  active remains three and the FIFO head is queued, never unknown, under
  capacity pressure.
- Feature documentation for Python construction, config v1/v2, ownership,
  deferral, renewal limitations, safe status, logs, tests, and opt-in real
  accelerator configuration.

Out of scope:

- Status mutation, raw environment/command display, live process reattachment,
  a log-follow command, a queue daemon/worker CLI, bulk enqueue, suite-level
  downstream fail-fast, real GPU discovery, and making opt-in hardware tests a
  `validate-pr` requirement.

Assumptions:

- The selected pool exists and status reports all queue-item statuses in that
  pool, regardless of owner. Optional live inspection is used only when the
  supplied adapter proves same-session ownership.
- Persisted acquisition evidence can be older than the latest successful lease
  renewal; the read model labels it instead of implying it is live authority
  truth.

## Fixed Contracts And Private Discretion

- Observable behavior: counts and active rows describe the same repository
  snapshot; terminal counts are separate; active equals claimed plus
  dispatched; active limit is explicitly labeled controller-local. Text and
  JSON expose equivalent facts.
- Public or durable shapes: repository/service exposes the selected-pool
  snapshot needed by status without promising a general query API. The pool
  read model's `to_dict()` uses named count fields and active rows, never
  arbitrary evidence. CLI adds only `--pool`; scheduling remains Python-first.
- Trust and failure boundaries: malformed or broad legacy evidence is treated
  as unavailable safe assignment data, not passed through. Live observation
  failure does not corrupt persisted status and is labeled as observation
  uncertainty.
- Cross-phase contracts: no modification to Phase 1 mutation guards or Phase 2
  evidence allowlist/lifecycle ordering. The example uses public construction
  and the built-in static provider.
- Reproducibility and compatibility: list ordering is stable; queue config v1
  status still works; existing service/item fields remain. Generic docs use
  `slot-a`/`slot-b`; one clearly marked downstream-style snippet may use
  `CUDA_VISIBLE_DEVICES` as ordinary authored config.
- Private choices the executor may simplify: exact read-query grouping, text
  whitespace, example command content, and whether counts are a nested record
  or direct typed fields, provided `to_dict()` is stable and explicit.

## Proportionality

- Existing seam reused: queue-item indexed columns, service/status builders,
  CLI envelope/formatter, persisted safe handle evidence, and v22 example
  metadata/testing conventions.
- Material additions and current justification: one pool snapshot is needed by
  the operator view; the safe summary replaces broad raw evidence; one default
  e2e proves the motivating persistence/coordination/process workflow.
- Optional hardening and future capability deferred: pagination/tag/submission
  indexes, streaming status, TUI, log following, metrics/utilization, hosted API,
  and hardware discovery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Pool counts and active rows agree for one repository snapshot. | SQLite repository/read model | Separate reads race with completion/refill. | Contradictory operator status. | Transactional read integration with state changes before/after. |
| New pool status never exposes unsafe evidence. | Status read model | Legacy/current handles contain broad mappings. | Secrets or command details leak. | Explicit forbidden-key/value tests for current and legacy rows. |
| Persisted facts are not described as live observation. | Status read model | Separate CLI has no adapter process memory. | Operators infer false liveness/renewal. | Source labels with and without same-session adapter. |
| Twelve-over-three never exceeds three or reuses one live slot. | Controller, provider, local adapter | Refill or cleanup race crosses all prior phases. | Resource overlap. | Real SQLite queue/coordination causal integration. |
| Text and JSON represent the same selected-pool facts. | Shared read model; CLI is presentation only | Formatter independently recomputes counts/evidence. | Output drift. | Contract comparison against one `to_dict()` model. |

## Implementation Slices

1. Add the deterministic repository/service pool snapshot and its contract and
   SQLite integration coverage; keep reusable query helpers private.
2. Build the allowlisted pool-status/active-attempt models, evidence-source
   labels, and legacy-evidence redaction tests.
3. Add `--pool`, JSON envelope compatibility/version handling, and text rendering
   from the same model; retain current service/item status paths.
4. Add the generic two-slot operations example and the twelve-over-three
   success/failure/cancellation integration/e2e proof.
5. Update queue/resource/run-store/preflight/reliability/CLI/testing docs and
   run all Stage 23 and repository validation gates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public status/read models and import boundaries. | Intentional exports import cheaply; queue import has no vendor/CLI side effect. |
| Unit | required | Count/read model, allowlist, source labels, and formatter parity. | Every status count; malformed/legacy evidence omitted; no forbidden values. |
| Contract | required | Pool snapshot and stable status JSON/envelope. | Selected-pool counts/order, exact safe keys, and text/JSON fact parity. |
| Integration | required | Twelve-over-three and repository snapshot behavior. | Exactly three active/unique slots; one replacement; failed/cancelled capacity returned; eventual terminal states. |
| E2E / opt-in | default dependency-free e2e required; hardware profile deferred/manual | Public Python/CLI example, separate logs, visible assignments. | Three commands over two generic slots; manual accelerator snippet is never collected by default. |

Targeted commands:

    uv run pytest tests/contracts/test_queue_repository_contract.py tests/contracts/test_queue_python_api_contract.py tests/contracts/test_queue_config_contract.py
    uv run pytest tests/integration/queue tests/e2e/test_queue_cli.py
    uv run pytest tests/unit/loom/queue
    uv run python -m tools.test_harness run e2e

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: snapshot-inconsistent counts, accidental raw-evidence passthrough,
  overstating live status, flaky timing/process tests, or documentation implying
  distributed-limit or crash-safety guarantees.
- Review focus: SQL snapshot queries, exact JSON/redaction contract,
  persisted/live wording, deterministic fake-clock/process synchronization,
  example metadata, and absence of scheduling in CLI.
- Stop if: stable counts require queue DDL not justified by measured evidence;
  Phase 2 did not persist enough safe data for the accepted status; or the e2e
  requires sleeps/external hardware rather than deterministic synchronization.
- Accepted debt and revisit trigger: no general queue query API until a second
  consumer or measured scale needs filters/indexes; real hardware remains
  opt-in until a portable acceptance environment exists.

## Executor Handoff

- Read section range: this entire phase plan plus planning requirements `FR-10`
  through `FR-12`, the `Examples And Validation` section, and decisions `A-4`
  through `A-7`.
- Safe implementation slices: execute slices 1-5 in order; keep repository,
  read-model/CLI, e2e, and documentation commits coherent.
- Decisions not to revisit: no raw evidence, new worker/log-follow command,
  hardware default gate, provider recovery, distributed quota, or generic
  scheduler policy.
- Conditions requiring manager action: any stop condition, an incompatible
  status-envelope change beyond a v2 bump, or a need to reopen the Phase 2 safe
  evidence contract.

## Workflow State

- Manager preparation: complete in Stage 23 planning
- Expanded planning: required after Phase 2 merge; pass unused
- Implementation: not started
- Refiner: optional for a qualified implementation/test blocker; unused
- Pre-submit gate: not run
- Independent review: required after implementation; unused
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none recorded |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
