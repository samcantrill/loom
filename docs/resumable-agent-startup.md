# Resumable agent startup implementation

Status: in progress. Branch `codex/resumable-agent-startup`, based on deployed
revision `77088c3b01bcc3afd6f6789e662310832ffd46f7`. This is an incident correction,
not a numbered roadmap phase. Apollo's targeted containment and guarded release
have completed; permanent fleet rollout remains in progress.

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

## Targeted namespace recovery (authorized follow-up)

Apollo has one unresolved launch and 20 contained historical launches. Its PID
namespace is isolated, while its cgroup is shared with SSH. The user authorized
implementing a targeted alternative to host reboot. `agent-recover-namespace`
adds a cancellation-only local authority boundary: exact boot/birth identities,
authenticated original owner, stopped-agent lock, quiesced spawners, exclusive
lineage, pidfd termination, then positive completion and an atomic receipt.
Ordinary startup still cannot adopt stored PIDs. Pending interrupted proof holds
claims; a completed exact-launch marker requires guarded coordinator recovery.

Focused evidence: six unit/CLI checks and two real-Singularity cases pass
(successful recovery/replacement/replay with a surviving peer; interruption after
namespace exit retaining uncertainty). The existing guarded-close integration
passes with the exact-launch marker, an unqualified success file and a lost
release reply; it settles CANCELLED and releases the original session's claims.
Source/test Ruff and Pyright pass; existing boot-recovery integration also passes.
The locked bundle for `26c919cd` was published and installed as a candidate on
Apollo. Native recovery `apollo-namespace-recovery-20261113` contained the original
namespace, launcher and supervisor without reboot; successful exit is false.
The user's protected scheduling reload authorized `recover_unknown` at revision
15; temporary permission was removed at revision 16 after guarded release.

Live admission exposed two additional recovery gaps: a GRANTED launch may have no
process-start event, and drain clears the current-offer bit. Recovery now uses
the existing deterministic root identity only for that pre-acknowledgement state,
and requires all retained session offers to have expired even after drain.
The exact agent-owned containment evidence remains mandatory. A focused HTTPS
integration reproduces missing acknowledgement plus drain, rejects a fresh offer
and wrong root, closes CANCELLED, and releases the same session after a lost
release response. This and the existing reboot case pass; changed source/test
Ruff and Pyright pass. Commit `4800c191` was published as a locked, offline-verified
bundle and installed on the coordinator host. A temporary recovery coordinator
using that candidate and Apollo's recovery-only candidate client completed
`apollo-namespace-close-20261113`: authority CANCELLED at revision 52, remote
assignment RELEASED, zero local retained assignments and provider claims. The
recovery supervisor shut down cleanly. Both original managed services were
restored with retained root/session identities. Apollo remains drained for the
permanent fleet upgrade. No host reboot or workload-image rebuild was needed.

## Remaining rollout work

Rollout uncovered a retained authorization receipt from an older coordinator
epoch on Calypso. Replaying it attempted backward reconciliation and reused a
key with different session content. Authorization replay now selects an epoch
only through a fresh handshake, consuming historical revisions without moving
the session backwards. The TLS regression replays 66 expired receipts across a
coordinator restart and verifies successful publication/release.

Runtime upgrades can explicitly borrow an existing empty closed maintenance
gate using `--maintenance-id`; they retain its owner/digest, revoke their check
permissions and leave the gate closed after completion or abort. This lets the
deployment preserve the user's scientific-admission hold without an open window.
Validation: both authorization-history TLS cases pass; six gate binding,
restoration/abort and CLI checks pass; an actual disposable SSH/native-service
runtime upgrade completes while preserving the original closed gate and revoking
its check permissions (208.93 seconds). The develop merge passes 41 affected
accepted-time, observation and GPU-policy checks. Ruff/diff checks pass. Pyright
reports no errors in changed runtime owners; the Fleet CLI reproduces the same
25 pre-existing optional-result diagnostics on its unchanged baseline. The live
read-only upgrade preflight reaches all 12 agents and the coordinator.

The user cancelled current and future scientific work on November 13. Maintenance
gate `stop-pos-for-loom-fixes-20261113` is closed, and MMPD cancellation was accepted.
Complete physical settlement before replacing services. UBFC retry, scientific
canary completion and full-matrix submission are removed from the active scope;
leave scientific admission closed after bounded infrastructure qualification.

- Finish release build/publication after the targeted gate below. Agents and
  supervisors must be upgraded together after settlement; the workload worker
  contract has not changed.
- Run only checks affected by further edits. The repository's unparameterized
  `make validate-pr` runs whole lanes; the task's explicit focused-validation rule
  takes precedence. Record the targeted gate and build evidence for the release.
- All four original Apollo process identities are gone; the Linux boot is
  unchanged. Guarded close, release, service restoration and permission revocation
  are complete. The fleet still selects its original runtime release.
- Upgrade through the fleet lifecycle after settlement and qualify the deployed
  release with bounded infrastructure checks. Keep scientific work stopped.

No total startup deadline is introduced. Genuine failed ownership remains UNKNOWN.
Runtime rollout and scientific acceptance remain
unverified; no claim of completion is made.
