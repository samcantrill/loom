# Resumable agent startup implementation

Status: complete. Runtime activation, qualification and administrative restoration
are verified; scientific admission remains closed. PRs #469 and #470 are merged, with deployed runtime revision
`d4daab963b6739e2dcc9971f8e5c54fee014744d`. This is an incident correction,
not a numbered roadmap phase. Scientific work remains stopped.

## Accepted scope

Implement the user-approved startup/delayed-communication plan: finite namespace
observations with creation-owned handles; exact replay; finite cooperative service
calls; cancellation before grant; retained containment evidence; truthful offer and
admission diagnostics; nearby timeout regressions; supported recovery, fleet
upgrade, and delayed and normal peer infrastructure qualification. The user
cancelled scientific recovery, canaries and matrix submission from the active scope. Preserve genuine unknown-owner admission holds,
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

Validation used an isolated Python 3.12 environment installed editable against
this worktree with locked config, fleet and MCP extras. The first integration
attempt used the main checkout's interpreter, whose protected child environment
imports that other checkout; those four failures are superseded by the isolated
environment's passing run. Do not use `PYTHONPATH=src` plus the main checkout
interpreter for worker integration tests.

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

The permanent coordinator, all twelve agents and all twelve supervisors now run
`loom-d4daab96`. All 24 CPU/storage checks and all twelve nonexclusive GPU
capability checks pass. The original Apollo process identities are gone and its
boot identity is unchanged; guarded close/release and permission revocation are
complete. Calypso's result and retained claims have settled. The upgrade restored all twelve drained policies, revoked all temporary check
permissions and completed with the original maintenance gate closed and settled.

No total startup deadline is introduced. Genuine failed ownership remains UNKNOWN.
Infrastructure qualification does not establish POS scientific acceptance, which
is deliberately outside the active scope.

### Obsolete pending reconciliation discovered during rollout

The fixed installed client settled Calypso's contained result and released all
retained assignments/provider claims. The old agent then remained stuck before
publishing its live session identity: its journal retained a backward
reconciliation created by the old authorization replay bug. The coordinator
rejected that exact request, but startup replay treated it as permanently pending.

Pending reconciliation now retires an intent only after a definite protocol
conflict and a fresh handshake proving its target epoch is obsolete. Current-epoch
conflicts and indeterminate transport outcomes remain errors with the intent
retained. No session, claim or launch evidence is invented or overwritten.
The existing TLS journal replay test now reproduces the legacy backward request,
retains it through uncertainty, retires it after confirmed rejection, and verifies
the current session is unchanged. That test and the coordinator-restart
authorization-history regression pass (2 checks); changed-file Ruff, diff checks
and source Pyright pass. No full-suite claim is made.


## Verified deployment closeout — November 13, 2026

Operation `loom-startup-fixes-20261113` completed through its retained successor
`runtime-candidate-3f5cb342ceb53c85f1caac75`. The fleet inventory selects immutable
release `loom-d4daab96`, descriptor SHA-256
`bb28f60266963edd827e2e33b418fb5eeb39589d46306e2b822581dfdcdf0617`.
The release and its build receipt live under
`/nas/home/can134/.local/share/rphys/submitted-workloads/releases/loom-d4daab96`.

Direct host verification confirms all thirteen native service roles and all
twelve authenticated supervisors execute that installed release. Original native
root/session identities and host boot identities are preserved; all thirteen
roles report settled. The coordinator and accepted-time clock are healthy, with
zero active admissions, waiting admissions and running assignments. The final
MMPD admission is CANCELLED. All twelve agents are drained with acknowledged
controls. Gate `stop-pos-for-loom-fixes-20261113` is closed and settled with no
remaining check permissions. Native completion and qualification receipts remain
in the protected fleet operation directory; temporary recovery tooling is not a
runtime dependency.

All 24 CPU/storage reports were verified and all twelve nonexclusive GPU
capability checks passed. Three report downloads needed another observation;
no check job was resubmitted. Policy restoration required successive exact
continuations because the existing restore loop dispatches controls sequentially.
No machine reboot, workload-image rebuild or scientific resubmission was needed.
Scientific validation remains cancelled until a new user instruction.
