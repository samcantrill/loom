# Phase 3 Execution Plan: Downstream Operations Proof

## Metadata

- Status: in_progress
- Roadmap stage and phase: 23-post, Phase 3
- Manifest: `docs/roadmap/stage-23-post/implementation-plan.md`
- Branch: `agent/stage-23-post-p3-downstream-operations-proof`
- Worktree root and path: `../loom-worktrees`; `../loom-worktrees/stage-23-post-p3-downstream-operations-proof`
- Base revision: `db382ac5fbc247b0345125e8c4d0d5a8abeceff4`
- PR target: develop
- PR title: `Managed Local Operations - Phase 3: Downstream Proof`
- Dependencies: Phase 2 remotely merged; branch must be based on refreshed `origin/develop`
- Requirement coverage: FR-1, FR-9, FR-10, FR-11, and FR-12
- Workflow path: fast; this phase applies the accepted runtime/recovery contracts to examples, docs, and e2e proof
- Blockers: none

## Objective And Context

- Vertical outcome: downstream users have one runnable, copyable managed-local
  example and concise operational guidance showing construction, maintenance,
  truthful status, graceful stop, crash recovery, a single item requesting two
  concrete slots, and a safe custom indivisible-bundle provider pattern.
- Earlier dependency: Phases 1 and 2 provide the complete public runtime,
  health/status, drain/cancel shutdown, and explicit unknown recovery surface.
- Later work explicitly out of scope: generic scheduler/resource-observation
  design from Stage 25, production GPU probing, a Loom daemon, reattachment,
  weighted slot schema, and packaging the example bundle provider as a core
  implementation.

## Current Source And Harness

- Relevant files and symbols:
  - `examples/operations/managed-local-queue/run_managed_local_queue.py`
    manually builds the service, static provider, adapter, and controller.
  - The script assigns `example-controller` only to the adapter while its
    controller uses `controller-1`, so live status falls back to persisted.
  - `examples/operations/managed-local-queue/README.md` explains only the
    Stage 23 manual construction and does not cover maintenance, shutdown, or
    recovery.
  - `tests/e2e/test_queue_cli.py::test_managed_local_queue_example_is_rerunnable`
    checks slots, logs, and counts but not `same_session_live` or a two-slot
    item.
  - `docs/features/queue.md` says callers should keep adapters alive and
    maintain cycles manually; it already distinguishes queue, authority, and
    delegated scheduler ownership.
  - `docs/roadmap.md` has stale Stage 23 status wording.
- Existing tests and seams:
  - `tests/unit/loom/queue/test_assignments.py` already proves a standard
    `resources={"gpu": 2}` request binds two static slots and compensates
    partial acquisition.
  - The example harness supports a dependency-free subprocess run in a
    temporary output root and verifies rerunnability/log contents.
  - Phase 2 integration tests prove crash recovery and lease retention; this
    phase should reference rather than duplicate their internal matrix.
- Import, dependency, or harness constraints:
  - Runnable examples must remain generic and dependency-free. Use
    `accelerator`/`LOOM_ASSIGNED_ACCELERATORS` in validated code; document
    `gpu`/`CUDA_VISIBLE_DEVICES` only as a downstream naming variant.
  - Do not add a GPU library, device probe, container dependency, or real
    authority service to default validation.
  - Keep the custom bundle provider in the example directory and label it as a
    project-owned pattern, not a stable core Loom provider.

## Scope

In scope:

- Rewrite the canonical managed-local script to construct
  `ManagedLocalQueueRuntime.from_spec(...)` instead of manually wiring provider,
  adapter, and controller.
- Put the owner in `controller.owner_id` and prove that one authoritative value
  reaches claims, adapter evidence, and same-session live status.
- Configure two generic accelerator slots through authored schema-v2 static
  assignments so the runtime factory proves config-to-provider construction.
- Enqueue at least one item with `resources={"accelerator": 2}` and assert its
  active assignment contains two distinct slot IDs/binding values. Keep later
  one-slot items to prove refill/concurrency and per-attempt logs.
- Drive the example through the runtime loop or its safe test-sized lifecycle,
  not a copied manual timing loop. Make process duration deterministic enough
  to observe active same-session status without slow tests.
- Strengthen e2e assertions for `same_session_live`, the two-slot item, final
  counts, distinct logs, and rerunnability.
- Add a small example-only paired/bundle assignment provider that implements
  `acquire`, acquire-all-or-rollback, `renew`, and `release` over the same
  physical member coordination keys used by individual allocation.
- Add focused tests proving bundle-versus-individual contention, partial
  rollback, both-member renewal/release, and a two-value environment binding.
- Expand the example README and `docs/features/queue.md` with:
  - minimal construction and `threading.Event`/signal-handler use;
  - who owns runtime, controller, provider, authority, and supervisor facts;
  - `READY`, `DEGRADED`, `RECOVERY_REQUIRED`, drain, cancel, and timeout;
  - external containment plus explicit `resolve_recovery_unknown` workflow;
  - persisted versus same-session versus unobserved hardware truth;
  - standard two-slot request versus an indivisible custom bundle;
  - POSIX built-in runner limitation and a minimal systemd `KillMode=control-group`
    deployment pattern;
  - one-runtime-per-pool and controller-local active-limit limitation.
- Correct the stale Stage 23 roadmap status and link the Stage 23-post plan
  without rewriting completed historical plans.

Out of scope:

- A production-ready generic topology library, built-in GPU pair provider,
  weighted static slot, bundle config schema, device-health check, or discovery.
- Treating the example provider as a supported public import outside its
  example directory.
- Real GPU, CUDA, SLURM, container, systemd, crash-kill, or authority-service
  execution in `make validate-pr`.
- CLI daemon/start changes, queue status-envelope changes, automatic recovery,
  retry/requeue, or process reattachment.
- Stage 25 stage-author, notification, resume, generic scheduling, or
  resource-usage observation work.

Assumptions:

- A short stdlib child process is sufficient to make active status observable
  deterministically while keeping e2e runtime small.
- The example may create authority resource limits because it is self-contained
  test setup; the runtime itself still only validates and never provisions.
- Systemd text is an illustrative deployment pattern and does not become a
  required Linux-only acceptance test.
- The downstream GPU spelling is safe to show in docs because Loom treats the
  resource/binding names as authored generic strings and contains no vendor
  behavior.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - Canonical output identifies one active two-slot item with two distinct
    slots and `source=same_session_live`.
  - All example items finish, each attempt has distinct stdout/stderr paths,
    expected stdout content is present, and reruns preserve prior evidence.
  - Bundle and individual provider paths contend on identical physical member
    keys; no synthetic bundle lease can bypass member ownership.
  - Docs state that recovery confirmation is an operator assertion and that
    Loom never releases foreign leases.
- Public or durable shapes:
  - No new core public API is introduced in this phase.
  - The example imports the Phases 1-2 surface exactly as documented.
  - Example output remains human-readable and test-owned, not a durable CLI
    envelope.
  - Queue/config/evidence/database shapes remain unchanged.
- Trust and failure boundaries:
  - The systemd/supervisor owns process-tree containment; runtime owns recovery
    gating; authority owns lease expiry/fencing.
  - Persisted queue evidence is not described as current hardware or lease
    availability.
  - Example bundle code is project-owned placement logic and must never access
    queue repositories or controller mutation.
- Cross-phase contracts:
  - Use the exact owner, state, serve/shutdown, status, and recovery behavior
    merged in Phases 1-2; do not create a second convenience wrapper.
  - Preserve Stage 24's candidate-policy ownership and Stage 25's broader
    design boundary in docs.
- Reproducibility and compatibility:
  - Example output root remains caller-selectable and each run uses a unique
    directory.
  - Example commands use only stdlib Python and local SQLite/in-memory-capable
    public stores available in the existing test environment.
- Private choices the executor may simplify:
  - Exact item count/order, child sleep duration, printed labels, README
    section order, and the example provider's local helper names, provided all
    acceptance behavior remains clear and deterministic.

## Proportionality

- Existing seam reused: the runtime, static provider, custom provider protocol,
  SQLite coordination store, pool status, and current e2e harness.
- Material additions and current justification:
  - A validated runtime example prevents the demonstrated manual-owner defect
    from becoming the downstream template.
  - A project-owned bundle provider pattern is needed because users explicitly
    asked how one indivisible placement can represent two devices without
    overlapping individual allocation.
  - Supervisor/recovery/status docs are needed because the safety boundary is
    partly operational and cannot be inferred from API names alone.
- Optional hardening and future capability deferred: generated docs, a provider
  SDK/package, GPU-server acceptance profile, actual systemd test, telemetry,
  dynamic discovery, and built-in topology algorithms.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Example uses one owner | Runtime/config | Manual adapter/controller construction | Persisted-only status and ambiguous lifecycle ownership | E2E `same_session_live` and owner fields |
| One item can own two slots | Static provider/authority | Incorrect request/config wiring | Partial or duplicate assignment | Active status has two distinct slots/binding values |
| Bundle owns physical members | Example custom provider/authority | Synthetic independent bundle key | Bundle and single-slot jobs overlap hardware | Contention test on identical member keys |
| Partial bundle acquisition rolls back | Example provider | Second member unavailable | First member leaked and capacity stranded | Store counter/lease assertions |
| Documentation does not overclaim live truth | Queue/runtime status docs | Persisted expiry/status read as hardware health | Unsafe operator action | Wording review plus source labels in e2e |
| Crash containment owner is explicit | External supervisor/operator docs | Runtime assumed to kill/reattach foreign work | Orphan process survives lease expiry | Recovery guide checklist and exact API snippet |

## Implementation Slices

1. Convert the canonical script/spec setup to the managed-local runtime with
   one config-owned owner and authored static assignments.
2. Shape deterministic work so one active item requests two slots, later items
   prove refill, and output/status/log assertions remain rerunnable.
3. Add the example-only bundle provider and focused member-lease lifecycle
   tests; keep it independent from repository/controller code.
4. Rewrite the README and queue feature sections around the recommended API,
   supervisor/recovery checklist, status truth, multi-slot/bundle choices, and
   operational limitations.
5. Strengthen e2e/package checks, correct Stage 23 roadmap status/linkage, and
   run full validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Documentation example uses supported public path | Managed-local module/API already covered; no example-only core export |
| Unit | required | Bundle provider lease lifecycle | Acquire-all/rollback, contention, renewal, release, binding, safe evidence |
| Contract | required | Existing provider/runtime contracts remain sufficient | No new core contract; rerun queue Python/resource contracts |
| Integration | required | Runtime plus standard two-slot provider | One request owns two distinct physical leases and refills later work |
| E2E / opt-in | required default e2e | Copyable script, live status, logs, rerun | `same_session_live`, two slots, expected counts/content, two preserved run roots |

Targeted commands:

    uv run --extra config pytest tests/unit/loom/queue/test_assignments.py tests/unit/loom/queue/test_managed_local_runtime.py -q
    uv run --extra config pytest tests/contracts/test_queue_python_api_contract.py tests/contracts/test_queue_managed_resources_contract.py tests/contracts/test_queue_config_contract.py -q
    uv run --extra config pytest tests/integration/queue/test_managed_local_runtime.py tests/integration/queue/test_managed_local_controller.py -q
    uv run --extra config pytest tests/e2e/test_queue_cli.py::test_managed_local_queue_example_is_rerunnable -q

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: example timing could be flaky; provider code could become an
  accidental core promise; bundle ownership could use a synthetic key; docs
  could imply persisted status is live or that the runtime supplies a daemon,
  hardware check, or reattachment.
- Review focus: copy/paste simplicity, deterministic e2e behavior, one owner,
  two distinct slots, same physical keys for all allocators, rollback and
  release, explicit supervisor boundary, and no domain/vendor logic in core.
- Stop if:
  - the example needs real GPU/container/SLURM/systemd dependencies;
  - deterministic active observation requires an unbounded or flaky sleep;
  - a safe bundle pattern needs a new core schema or provider contract;
  - documentation cannot explain recovery without implying automatic process
    verification or lease takeover;
  - the current dirty `docs/roadmap.md` state cannot be reconciled safely from
    the dedicated phase worktree.
- Accepted debt and revisit trigger: the bundle provider is a copyable pattern,
  not a supported library. Revisit only after multiple downstream projects
  need the same topology abstraction.

## Executor Handoff

- Read section range: this entire phase plan, planning FR-1 and FR-9 through
  FR-12, and decisions FQ-6/FQ-7/DQ-5/DQ-6.
- Safe implementation slices: follow slices 1-5; first make the canonical
  standard two-slot runtime proof stable, then add the separate bundle pattern.
- Decisions not to revisit: generic validated resource names, GPU names only
  as docs variants, example-only bundle provider, physical member leases,
  no core schema/dependency, no daemon/reattachment claim.
- Conditions requiring manager action: any stop condition, a public runtime
  mismatch with prior phases, or a need to edit/rewrite unrelated Stage 24 or
  user roadmap work.

## Workflow State

- Manager preparation: complete at
  `db382ac5fbc247b0345125e8c4d0d5a8abeceff4`; Phase 2 remote merge and cleanup
  are verified, and the example/docs still contain the planned manual-owner,
  lifecycle-guidance, bundle-proof, and roadmap-status gaps
- Expanded planning: not needed
- Implementation: complete. The canonical example now uses the runtime factory
  with schema-v2 static assignments and one config-owned owner; the example-only
  paired-member provider, focused lifecycle tests, e2e proof, and operational
  documentation are complete.
- Refiner: not needed unless a qualified blocker is found
- Pre-submit gate: pending
- Independent review: not needed on the fast path; manager must review every
  operational claim against the merged runtime
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `examples/operations/managed-local-queue/` runtime example, metadata, README, and paired-member provider; focused provider unit test; e2e proof; queue/roadmap docs. No core/schema/dependency changes. |
| Tests added or updated | Added `tests/unit/loom/queue/test_example_paired_assignment_provider.py`; strengthened `tests/e2e/test_queue_cli.py::test_managed_local_queue_example_is_rerunnable` for owner, live status, two slots, bindings, logs, and reruns. |
| Validated revision/tree state and evidence | 2026-08-18 targeted checks passed: Ruff check/format; unit `21 passed`; contracts `14 passed`; managed-local integration `23 passed`; example e2e `1 passed`. `make validate-pr` and `make test-summary` remain manager gates. |
| Validation-relevant changes after evidence | None; this completion-record update is metadata only. |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
