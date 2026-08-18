# Phase 3 Execution Plan: Operator Status And End-To-End Proof

## Metadata

- Status: in_progress
- Roadmap stage and phase: v23 Phase 3
- Manifest: `docs/roadmap/stage-23/implementation-plan.md`
- Branch: `agent/stage-23-p3-operator-status-proof`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-23-p3-operator-status-proof`
- Base revision: `246fb29a4e16ec3130fac1e0ea726dd5d11fa0de`
- PR target: `develop`
- PR title: `Managed Local Concurrency - Phase 3: Operator Status and Proof`
- Dependencies: Phases 1 and 2 remotely merged with their cycle, evidence,
  config, ownership, and local lifecycle contracts intact
- Workflow path: expanded because status serialization/redaction, CLI envelope
  compatibility, and causal concurrency end-to-end evidence have durable impact
- Blockers: none; Phase 2 merged through PR `#210` as `7187829`, its merge
  metadata is on `develop` at the recorded base, and the phase worktree is
  isolated

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
  dispatched; active limit is explicitly labeled controller-local. Lifecycle
  status and counts always come from persistence; optional live inspection may
  enrich safe attempt facts but cannot rewrite those persisted facts. Text and
  JSON expose equivalent facts.
- Public or durable shapes: repository/service exposes only the selected-pool
  snapshot needed by status, not a general query API. The additive `pool`
  mapping in `QueueOperationalStatus.to_dict()` has exactly `pool_name`,
  `controller_max_active_items`, `counts`, and `active_attempts`. `counts` has
  exactly `queued`, `claimed`, `dispatched`, `active`, `succeeded`, `failed`,
  `cancelled`, and `unknown`; `active == claimed + dispatched`.
- Each `active_attempts` row has exactly `queue_item_id`, `status`, `owner_id`,
  `session_id`, `evidence_source`, `live_observation`, `process`, `assignment`,
  and `logs`. `evidence_source` is `persisted`, `same_session_live`, or
  `unavailable`; `live_observation` is `not_requested`, `same_session`, or
  `unavailable`. The nullable subdocuments are limited to `process` with
  `pid`/`pgid`, `assignment` with `provider_name` and `slots`, and `logs` with
  queue-relative `stdout_path`/`stderr_path`. A slot has only
  `resource_name`, `slot_id`, nullable `label`, `lease_id`, and `expires_at`.
  Claimed work may expose its persisted claim owner but has null session,
  process, assignment, and logs rather than fabricated handle facts.
- Trust and failure boundaries: the read model recognizes only the fixed,
  schema-v1 `managed_local` projection already persisted by Phase 2 and copies
  only the fields named above. Other `DispatchHandle.evidence`, unknown legacy
  keys, fencing/binding values, command/cwd, and environment names/values are
  never traversed into the pool model. Missing, malformed, or unsupported
  evidence yields null safe subdocuments and `evidence_source=unavailable`.
  A supplied adapter contributes live facts only after matching the persisted
  owner, session, and handle; mismatch or inspection failure retains any safe
  persisted facts and sets `live_observation=unavailable`.
- CLI compatibility: `loom queue status CONFIG` and `--item` retain their
  current result fields and `loom.cli.queue.status.v1` envelope. `--pool` adds
  only the `pool` mapping inside that same result and obtains any refreshed
  facts through the safe pool model rather than the broad legacy
  `active_items` serialization. The envelope remains the existing
  `schema_version`/`ok`/`warnings`/`result` shape. Only a necessary removal,
  rename, or retype may advance that same envelope constant to v2; no nested
  pool-status schema version or second envelope is introduced.
- Cross-phase contracts: no modification to Phase 1 mutation guards or Phase 2
  evidence allowlist/lifecycle ordering. The example uses public construction
  and the built-in static provider.
- Reproducibility and compatibility: list ordering is stable; queue config v1
  status still works; existing service/item fields remain. Generic docs use
  `slot-a`/`slot-b`; one clearly marked downstream-style snippet may use
  `CUDA_VISIBLE_DEVICES` as ordinary authored config.
- Private choices the executor may simplify: exact read-query grouping, text
  whitespace, example command content, Python class/helper layout, and nullable
  field representation before `to_dict()`; the serialized names and allowed
  values above are fixed.

Acceptance for the expanded-path risks:

- One selected-pool read returns every status count and the `CLAIMED` and
  `DISPATCHED` rows from one SQLite snapshot in `(enqueued_at, queue_item_id)`
  order; rows and counts cannot represent opposite sides of one transition.
- JSON and text for the same model contain the same selected pool, limit,
  counts, attempt identities, source labels, and safe facts. Existing no-pool
  and item invocations retain their current v1 contract.
- Current, broad legacy, malformed, and unknown-version evidence serialize to
  the exact allowlist above, and secret sentinel keys and values appear in
  neither JSON nor text. Observation failure remains distinguishable from the
  absence of persisted safe evidence.
- The real-SQLite proof starts items 1-3 on three unique slots, observes item 4
  still queued while capacity is full, and then proves in order that a success,
  a non-zero exit, and a cancellation each releases capacity before exactly one
  FIFO replacement starts. The run never exceeds three active items or gives
  one live slot to two items; all twelve finish as ten succeeded, one failed,
  and one cancelled, with zero unknown.

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
| Unit | required | Count/read model, allowlist, source labels, and formatter parity. | Exact pool/count/row key sets; claimed null facts; current/legacy/malformed/unknown-version projections; nested forbidden-key and forbidden-value sentinels absent from both renderings; live identity match, mismatch, and inspection failure labels. |
| Contract | required | Additive pool status and existing CLI envelope. | No-pool and `--item` retain the v1 envelope/result; `--pool` adds only the fixed pool mapping; exact safe keys and text/JSON fact parity; no second or nested status version. |
| Integration | required | One-snapshot read and causal twelve-over-three behavior. | A second SQLite connection crosses a controlled read/transition barrier without producing mixed rows/counts. With real SQLite queue and coordination stores, controlled process gates prove 1-3 active, item 4 queued unchanged at capacity, then success->4, non-zero->5, cancellation->6 refills; active and simultaneous slot ownership peak at three; final counts are 10/1/1/0 for succeeded/failed/cancelled/unknown. |
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
- Review focus: one SQLite snapshot boundary; the exact pool/count/attempt key
  sets; allowlist construction rather than recursive evidence filtering;
  forbidden-value as well as forbidden-key coverage; same-session live proof and
  observation-failure labels; unchanged no-pool/item v1 envelopes; controlled
  success/failure/cancellation release-before-refill barriers; example metadata;
  and absence of scheduling policy in CLI.
- Stop if: stable counts require queue DDL without measured evidence; the fixed
  pool mapping cannot be added while preserving existing no-pool/item v1
  fields; safe attempt facts require a migration, raw/unknown evidence, or
  provider-private recovery data beyond Phase 2's `managed_local` projection;
  same-session ownership cannot be established without widening a public
  adapter contract; or the causal proof requires fixed sleeps, timing-only peak
  sampling, external hardware, or a new orchestration abstraction instead of
  deterministic process/SQLite barriers.
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

- Manager preparation: complete on 2026-08-18 against `246fb29`; manifest and
  phase-plan consistency, predecessor merge, repository identity, current
  source/test seams, and worktree isolation verified
- Expanded planning: completed on 2026-08-18 against `13f8512`; durable status
  redaction, additive CLI envelope compatibility, and the causally interacting
  twelve-over-three proof have fixed acceptance and stop conditions
- Implementation: complete on 2026-08-18; awaiting manager pre-submit/review
- Refiner: optional for a qualified implementation/test blocker; unused
- Pre-submit gate: not run
- Independent review: required after implementation; unused
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added selected-pool SQLite snapshots, allowlisted pool/attempt status models, `status --pool`, shared text rendering, and the managed-local operations example in `src/loom/queue/{repository.py,_sqlite.py,service.py,status.py,__init__.py}`, `src/loom/cli/{queue.py,formatting.py}`, `examples/operations/managed-local-queue/`, its inventory, and Phase 3 feature documentation. |
| Tests added or updated | Added pool-snapshot repository contract coverage; unit coverage for exact status keys, redaction, claimed null facts, additive legacy shape, and same-session labels; and queue CLI envelope/pool e2e coverage. Targeted queue matrix passed: 15 contract, 27 integration/e2e, and 79 unit tests. |
| Validated revision/tree state and evidence | Final gate passed against the implementation tree: `make validate-pr` completed Ruff, Pyright (0 errors), default harness (2,051 passed), config-extra harness (128 passed, 3 skipped), and `uv build`. `make test-summary` wrote `build/test-summary.md`: package 112, unit 1,444, contract 267, integration 180, e2e 48, config-extra 128 passed (3 skipped). Implementation commit `e0ee341`; removal-only generated-example cleanup `1f5b1d0`. |
| Validation-relevant changes after evidence | None. The only post-gate change before this record was removal of an accidentally generated example SQLite file. |
| PR, review, and merge | pending |
| Residual risk and cleanup | No known Phase 3 blocker. Accepted controller-local limit, crash-time/re-attachment, persisted-acquisition-versus-live-observation, and static-inventory risks remain. Worktree/branch/PR cleanup are manager-owned. |
