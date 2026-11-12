# Resumable agent startup implementation

Status: in progress. Branch `codex/resumable-agent-startup`, based on deployed
revision `77088c3b01bcc3afd6f6789e662310832ffd46f7`. This is an incident correction,
not a numbered roadmap phase. No deployment or live assignment mutation yet.

## Accepted scope

Implement the user-approved startup/delayed-communication plan: finite namespace
observations with creation-owned handles; exact replay; finite cooperative service
calls; cancellation before grant; retained containment evidence; truthful offer and
admission diagnostics; nearby timeout regressions; supported recovery, fleet
upgrade, delayed and normal peer qualification, UBFC recovery and POS canary checks
before the full scientific matrix. Preserve genuine unknown-owner admission holds,
credential expiry, bounded physical-effect slots, and scientific outputs.

## Current evidence

The initial supervisor correction replaces the two-second namespace loop with one
probe per query. A volatile pending-handshake map retains the original Popen;
reopened databases cannot reconstruct it. Cancellation acceptance and gate writes
share the operation lock. Late namespace discovery after cancellation supplies
containment evidence without opening the gate. Failed gate writes retain the
existing conservative unknown transition. The service now calls a finite
`launch_once`; synchronous clients retain `launch` joining convenience.

Validation checkpoint:

- 10 focused supervisor tests pass, including two pending namespace handshakes
  alongside a normal peer, accepted stop before grant, and incomplete containment.
- 10 process-group tests pass, covering creation ownership, signal ordering,
  shared cleanup budgets, and real unreaped-root success evidence.
- 5 concurrent-service integration cases pass: resident ceilings (1 and 2),
  live-starting recovery, unknown-owner admission hold, and starting cancellation.
- 4 further concurrent-service regressions pass: cancellation during recovery
  backoff, lost release while control stays responsive, and two bulk holds
  (parameterized).
- 4 operator-observation cases pass with explicit offer freshness and compatible
  connected semantics. The stale fixture advances 61 seconds within clock policy
  instead of jumping decades and accidentally testing clock degradation.
- Changed-source Pyright: zero errors/warnings. Changed-file Ruff and diff checks pass.

Use the isolated environment `/tmp/loom-startup-validation-ZOHywI/venv` for further
validation. It is installed editable against this worktree with locked config,
fleet and MCP extras. The first integration attempt used the main checkout's
interpreter, whose protected child environment imports that other checkout; those
four failures are superseded by the isolated-environment passing run. Do not use
`PYTHONPATH=src` plus the main checkout interpreter for worker integration tests.

Service recovery now uses finite queries. Containment and stop joins use existing
cooperative progress, yielding their delays instead of retaining an external
worker. Known incomplete cleanup retains ownership as pending; absent namespace
proof after launcher exit remains unknown. Operator observations distinguish
freshness from transport liveness. Private supervisor receipts now include startup
reason and elapsed time; rate-limited agent diagnostics report unknown-ownership
admission holds without claiming network failure.

## Additional qualified behavior

- Pre-cleanup success survives repeated incomplete containment observations (real
  zero-exit process, cleanup/reaping, delayed confirmation, durable reopen).
- Startup remains pending after a controlled 120-second observation interval.
  A competing host reaper losing the owned root instead produces UNKNOWN.
- Real Singularity startup with a three-second wrapper delay passes alongside a
  normal native peer, for both eventual execution and cancellation before grant.
  Neither test changes runtime settings or pulls/builds an image. Qualification
  uses the approved ca610797 SIF already published by rphys (14.44 seconds total).
- Endpoint startup observation timeout retains the original service; shutdown
  observation timeout can reobserve that same owner. The selected IPC deadline
  cases pass, including authentication and partial replies (9 checks total).
- Lost launch replies, pending physical-effect saturation, synchronous service
  lifecycle, and receipt decoding pass (6 selected checks).
- Transfer expiry, >64 expired authorizations, and exact-byte indeterminate poll
  replay pass (3 integration cases).
- Unknown-owner admission logs are asserted against a live integration case.
  Offer expiry plus lost rejection recovers the same assignment in the same epoch.
  Its initial fixture bypassed cooperative progress in fault wrappers; correcting
  those wrappers passes without extending the watchdog (45.17 seconds total).
- Changed-source/test Pyright and Ruff pass. Validation logs are task-owned under
  `/tmp/loom-startup-validation-ZOHywI`, not deployment dependencies.

## Review and release gate

The delayed accept/cancellation regression passes after observing the actual
five-second attempt fail, then releasing cancellation delivery. It preserves the
peer and launches no cancelled worker. Endpoint retry now retains the creator's
original Popen through repeated observation timeouts; its regression proves one
physical spawn across two timed-out attempts. The existing native service lock
continues to exclude competing application owners; no PID-based adoption is added.

Concurrency review found and corrected global-lock filesystem IO at gate
publication. The ordering lock is now per assignment, and IPC stop acceptance
returns a pending observation while that assignment's gate publication owns the
lock. A held-write regression proves an unrelated stop remains responsive. The
reviewed real Singularity execution/cancellation pair passes again (14.46s).
The reviewed startup, gate, ownership and exact-replay tests pass.

Source Pyright and changed-file Ruff pass. Expanding Pyright to the concurrent
integration test found 15 pre-existing errors in its provider-factory annotation
and two unrelated observation subscripts. Checking the base revision reproduces
those same errors (plus the relocated baseline file's relative-import error).
No new source/test errors were introduced by the reviewed changes. Whole-lane
`make validate-pr` is deliberately not substituted for the task's targeted gate.

## Remaining work and validation

- Finish release build/publication after the targeted gate below. Agents and
  supervisors must be upgraded together after settlement; the workload worker
  contract has not changed.
- Run only checks affected by further edits. The repository's unparameterized
  `make validate-pr` runs whole lanes; the task's explicit focused-validation rule
  takes precedence. Record the targeted gate and build evidence for the release.
- Inspect supported live recovery and fleet lifecycle paths. Read-only Apollo
  inspection still shows its original supervisor 1689457, root 1982595, namespace
  init 1982815, and gated worker 1982839 alive. The old owner cannot gain new live
  code/handles from replacing files. Retain claims until supported containment or
  boot recovery proves settlement; no live mutations have occurred.
- Upgrade through the fleet lifecycle after settlement, qualify the deployed
  release, recover UBFC preserving valid outputs, and finish profiling/scientific
  canary acceptance before submitting the full scientific matrix.

No new persistent schema or total startup deadline is planned. Genuine failed
ownership remains UNKNOWN. Runtime rollout and scientific acceptance remain
unverified; no claim of completion is made.
