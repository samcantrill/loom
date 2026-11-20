# Coordinator responsiveness implementation

Worktree: `/nas/home/can134/work/loom-worktrees/coordinator-responsiveness`.
Merged responsiveness change: `codex/coordinator-responsiveness`, based on
`develop` at `19f6a5e5`, with `b8db3e6b` integrated before landing.
Follow-up branch: `codex/slow-publication-recovery`, based on merged `c65af543`.
This is a focused maintenance change, not a numbered roadmap stage.

## Accepted scope

Slow reconciliation must not block healthy offer renewals, bounded work polls,
status, or recording cancellation. Preparation is disposable; durable admission,
reservation, binding, grant, release, replay and recovery records remain the
execution authority. Offer expiry never releases running ownership. Session
replacement, cancellation and scheduling changes fence incompatible prepared
work. Keep the existing 30-second offer lifetime.

Ready-stage preparation retains up to 32 stage owners with two I/O workers.
Request construction, input descriptors and recovery-predecessor inspection
share one slot keyed by run/stage. A completed prerequisite is retained until
dispatch, cancellation or supersession; it is never evicted to admit another
stage. At capacity, later stages report `stage_preparation_capacity` and retry
after an owner leaves. This bounds preparatory storage work, not CPU/GPU jobs
or scheduler submissions. Running obsolete writers drain before slot reuse;
restart recomputes this disposable preparation from durable run records.

Admission reconciliation activates a newly bound run once. Revisiting a waiting
run does not clear its waiting reason or advance its revision merely to restore
the same state at the end of the turn; actual dispatch still activates it.
Global priority applies to runnable work. An off-page READY projection receives
a context-preparation opportunity before the admission scan takes the freed
slot, but unfinished preparation does not prevent an independently runnable peer
from launching.

Completed input-directory inspection is another stage-owned prerequisite. Its
separate execution pool has two workers/eight outstanding scans and at most 32
unconsumed owners. Completion frees execution capacity, while the prepared stage
retains the exact evidence until dispatch or invalidation. Neither completed
success nor failure is silently evicted to admit an unrelated scan; failure
retries also obey the execution bound.

Implementation obligations:

- Deterministic event/barrier regression tests against real slow dependencies.
- Existing phase diagnostics: dispatch/admission wait, state-lock wait and hold,
  context loading, provenance validation, authority observation, result
  verification, scheduling preparation and commit. Report outside locks;
  diagnostic failures cannot change results.
- Separate reconciliation serialization from short coordination transitions;
  no filesystem/network work under global state locks or control write transactions.
- Two bounded context preparation workers, one pending operation per admission,
  fair rotation, only consume completed futures, retain occupied slots until
  actual completion; stale results cannot launch work; restart recomputes.
- Audit renewal, publication, polling, cancellation, start permits, replacement,
  HTTP bulk/control capacity and existing agent progress lanes.
- Bounded context reuse keyed by all captured validated inputs, including runtime,
  plan, resolved config, composition and project contracts. Hash fresh bytes;
  decode/validate those same bytes; do not retain large provenance needlessly.
- Admission-filtered stage-work queries in both stores and eligibility refresh.
  Existing admission-leading unique index suffices.
- Reuse pending-verification optimization from `557cb75f`: already present in
  develop (later changes extend implementation matching); retain full validation
  at adoption.
- Preserve recovery restrictions, reboot evidence, replay identities, GPU failure
  ownership, late-result fencing and distinctions between deadlines/freshness/job timeout.
- Five-agent isolated qualification with representative 31–34 MB manifests and
  delays beyond offer lifetime; responsive renewal/cancellation, exactly one
  committed result, lost-response/restart replay, bounded queues/memory.
  Measure p99 renewal against <1s normal / <5s injected-delay targets.
- Document results and retained-state upgrade. Deploy preserving storage,
  journals and submission identities; resume existing OMIT MMPD and PURE
  submissions through retained operations after qualification.
- Review, validate, merge into develop, synchronize clean develop checkout.

## Validation selection

Use `.agents/skills/loom-targeted-validation/SKILL.md`. Exact checks expand with
identified consumers, not a full-suite precaution. Initial owners:
`tests/unit/loom/queue/test_coordinator_responsiveness.py`,
`tests/unit/loom/queue/test_agent_sessions.py`,
`tests/unit/loom/pipeline/test_orchestration.py`, relevant production-daemon,
transport saturation, runtime-record/provenance, pending-verification, supervisor
lost-response and reboot-containment checks. Run changed-file Ruff, relevant
typing and diff checks. Physical deployment qualification is separate evidence.

## Implementation and validation

The manager worktree preserves the unrelated dirty original checkout. The change
uses a reconciliation guard, two read-only context workers and short state/control
transactions. Scheduling preparation and external authority effects retain their
existing operation identities; a final reservation gate rechecks epochs,
cancellation, current sessions, offer freshness and replacement capacity. Local
input bundles remain durable before reservation. Reload preparation retries when
new scheduling references invalidate its snapshot.

A 16-entry process-local cache captures and hashes every document consumed by the
original loader. A hit avoids deep decoding, but still reads fresh bytes; misses
validate and parse exactly those captured bytes. The cache drops document bytes
after loading. Admission-filtered stage-work queries preserve deterministic order.

Agent input/output IO, publication verification, result commitment, release
retention and recovery observations no longer hold the global state lock or a
control write transaction. Per-assignment guards serialize replay. HTTP reserves
capacity for control requests while bounding expensive handlers; actual completion,
not a caller timeout, frees a slot. Existing agent bulk/control/poll lanes remain
the execution architecture. Pending verification optimization `557cb75f` was
already present in the implementation base and remains unchanged.

Evidence (targeted selections; not a full-suite claim):

- 139 reservation, remote-delivery/transfer/publication, shared-recovery and
  responsiveness checks passed after the main lock split.
- 103 agent-session and responsiveness checks passed after narrowing replacement
  and offer-publication gates.
- 35 checks passed for cancellation/reload during blocked worker preparation,
  renewal during replacement observation, retained preparation reload and SLURM
  reservations.
- Seven integration checks passed for reboot containment, shared recovery and
  retry, mixed-route SLURM execution, and exact local observer recovery.
- Fourteen additional preparation/publication checks passed for cancellation,
  target reuse, local-file graphs, report projection and SLURM targets.
- Cache-specific validation: 47 checks passed across cache invalidation,
  LocalRunStore, production context loading and preparation contracts.
- Independent review identified a shared-publication fence still inside the state
  lock and missing background timing collectors. Both were corrected; 133 selected
  checks passed, including cancellation during blocked publication authority and
  rejection/replay across concurrent scheduling reload. Background context and
  scheduling spans reach the existing bounded diagnostic sink.
- Changed-source typing and Ruff passed. The existing transport test module has
  14 typing errors also reproduced from base `19f6a5e5`; these are not new errors.
- The existing malformed-pipeline report fixture fails on both base `19f6a5e5`
  and this branch because it mutates the obsolete `composition.resolved` field.
  Its injected producer raises KeyError before reaching the intended report
  validation. Other affected preparation cases are selected separately.

Five-agent qualification used five independent TLS identities, journals and real
resident supervisors on this host, with five 33,078,464-byte composition manifests.
Two blocked context reads occupied both preparation slots for 31.5 seconds. Four
agents continued renewal; the fifth deliberately stopped renewal to prove that
expiry cannot release its running assignment. Cancellation of both blocked
admissions completed while their underlying reads still occupied the slots.

| Measurement | Result |
| --- | --- |
| Normal renewal p99 (162 samples) | 0.603 s |
| Delayed-work renewal p99 (831 samples) | 0.035 s |
| Two cancellation acceptances | 0.028 s |
| Peak RSS growth during delay | 2,453,504 bytes |
| Final RSS growth from delay baseline | 8,753,152 bytes |
| Preparation operations pending during saturation | Exactly 2 |
| Scientific job launches and authoritative commits | Exactly 1 per job |

Lost renewal replies replayed the same receipt without extending expiry again.
A lost commit reply followed by agent-application restart resumed the same
supervisor and durable assignment; every job retained exactly one launch and
one authoritative attempt/commit. The final qualification includes enabled
background timing reporting. This qualifies coordinator responsiveness on
this machine, not fleet GPU, reboot or network failure behavior. The ordinary
30-second offer lifetime was preserved.

Reproduce the load qualification with the locked Python 3.12 development
environment and `pytest -q -s tests/integration/queue/test_coordinator_responsiveness.py`.
Use a short unique `/tmp` basetemp: native Unix socket paths have a length limit.
Disposable test artifacts and logs are task-owned under `/tmp`; no deployment may
depend on them.

## Delivery state

Final affected-consumer selection passed 276 checks. After independent review,
133 correction checks passed, and the five-agent qualification passed again with
background diagnostics enabled. Integration with `develop`'s diagnostic-binding
fix `b8db3e6b` passed 14 preparation/publication cases and 18 diagnostic composition
cases. The known obsolete malformed-report fixture remains a baseline failure.
Independent review passed on implementation head `50079b5225240b874697bb41071baa3022acfeba`.
[PR #462](https://github.com/samcantrill/loom/pull/462) owns the change and merge status.

Immutable release `loom-50079b52` was built in the configured durable release
location and passed offline installation/dependency/import verification. Its
descriptor is `/nas/home/can134/.local/share/rphys/submitted-workloads/releases/loom-50079b52/release.json`.
The source commit is the reviewed implementation head above; subsequent closeout
changes only documentation.

The user subsequently authorized cancellation of eight unfinished scientific
requests and three diagnostics, retaining valid completed stages for reuse.
Ten settled; Shazza retains one successful, contained prediction result under
the cancelled PURE-to-UBFC admission. Experiment chats will own resubmission.
The fleet still selects `loom-19f6a5e50e24`; all five agents are drained.

The image built from merged rphys `bbd352d3` and Loom `c65af543` passed installed
source, manifest, lock and dependency-origin checks. Its immutable digest is
`298354528e5913f94cab04548fe993391208bfd8e99b7155c3138d4585228ce1`.
The guarded `responsiveness-release-20261105` operation owns closed admission;
its driver is detached before service replacement while the follow-up is tested.

### Follow-up: slow publication and cancelled-result recovery

Live native evidence identified a second defect: Shazza's 174,848-member,
559,717,123-byte output closure took 2,002 seconds to hash and 940 seconds to
sync. The output declaration then rechecked its 60-second transfer grant and
rejected it as expired. Grant revisions 2 and 3 expired at 04:53:42 and 05:42:53
UTC on November 5. An unchanged retry repeats work that cannot meet the grant
lifetime. This is separate from coordinator lock responsiveness.

The bounded correction defines transfer expiry as a request-admission deadline.
An admitted declaration may complete verification after expiry; the commit
boundary still rechecks session, epoch, policy, fence and publication identity.
Future RPCs, including replay, still need an unexpired grant. There is no larger
timeout, verification cache, new durable state or weaker payload validation.

Deployment also needs a narrow extension of retained-result recovery: an ordinary
cancelled admission can qualify only if every outstanding assignment belongs to
the exact host-proved successful-result cohort and has an acknowledged native
containment receipt. The public cancellation record must refer to an
already-applied run operation bound to that same admission; it cannot admit a
pending preparation or target publication. This supersedes the original blanket exclusion of ordinary
cancellations for this demonstrated case. Live workers, unproved/missing results,
unresolved controls, unrelated cancellation, new cohort members, Slurm, capture
and target publication remain excluded. Recovery preserves journals and results;
normal replay and cancellation must settle before admission reopens.

Validation selects `test_result_runtime_recovery.py`, the three concurrent
publication/reload boundary cases, shared-publication replay/integrity cases,
and affected native runtime-upgrade recovery cases. Tests advance the accepted
clock beyond grant expiry during real TLS publication, prove a later expired
request still refuses, and exercise cancellation after real worker success with
native containment before result retention. Expand only for a failed check or
another affected ownership boundary. Fifteen selected checks passed, and normal
result replay through actual replacement passed after narrowing an outdated
metadata fault-injection fixture. The public cancelled-run replacement case
exposed its separate parent cancellation owner; the bound-admission correction
passed all seven affected recovery checks on `a427ca3a`, including public
cancelled-run replacement and cancelled-preparation candidate repair. Together
with the unaffected earlier results, all 17 selected cases pass. Changed-source
Pyright, changed-file Ruff and diff checks pass. Independent review passed on
`e7030dca` and confirmed the bound-admission correction on `a427ca3a`.

Immutable `loom-a427ca3a` was built from that reviewed source and passed offline
installation checks. Its descriptor SHA-256 is
`928b29ee72c24a4f8c00d169d0d262d14ae93315654a03873a799fdbe38693ce`.
It supersedes the unactivated `loom-50079b52` candidate. The prepared native
`responsiveness-release-recovery-20261105` operation selects this bundle and the
verified image; deployment remains pending until the follow-up merges.

### Slurm agent result storage and finite delivery turns

Agent-side result inspection, chunk reads and transport cleanup use two IO
workers, at most eight outstanding filesystem effects and at most 32 delivery
owners. An unfinished worker remains counted until it exits. The agent owner
alone advances report/chunk/commit state and writes its journals. A pending
read or cleanup does not stop another assignment's submission, observation or
cancellation. Both embedded and outbound Slurm use this path.

Delivery reads bounded report/manifest metadata and one transport chunk at a
time. The existing receiving assignment store checks the complete artifact
digest before finalizing it; this removes the sender's extra whole-file read
without dropping the receiver's integrity check. Lost chunk replies retain the
exact pending chunk. After agent restart, report/offset replay reuses the
receiver's durable acknowledged prefix. Cleanup requires acknowledged commit
or the existing exact release/cancellation authorization. Interrupted cleanup
can replay without reading already removed result files.

Scheduler polling cadence does not throttle result delivery. During an outbound
resident-work long poll, the same Slurm owner continues finite turns; the agent
still owns only one durable resident poll. Session-changing controls wait for
that poll's receipt, and offer maintenance resumes at its boundary. Slurm
command observation retains its existing cadence and pacing.

Stopping or reconnecting an outbound service interrupts its owned resident-work
and control long polls without waiting for their idle timeout. The existing
bounded HTTP monitor shuts down the socket; the occupied slot is released only
when the exchange returns. The original poll intent remains durable and is
recovered on restart. An interrupted exchange does not prove that the coordinator
rejected it, and it does not release a worker or its resource claims.

Recovery follows an exact retained supervisor launch while finite calls report
that acceptance is still pending. Cooperative service callers yield between
observations; synchronous recovery callers join the same operation. Neither path
creates a replacement launch identity.

Fault tests hold an actual result read while the same owner submits, observes
and cancels a peer, through embedded execution and the outbound TLS service.
Additional tests cover bounded IO capacity, chunk response loss with and without
agent restart, final-commit-before-cleanup and interrupted cleanup replay.
These fake-scheduler tests do not qualify an installed Slurm deployment.

Remaining timing/scale scope includes immutable input policy and CPU/GPU
preparation fairness; timeout/placement policy; paged reconciliation and
large-population qualification. Finite delivery exchanges still use the
existing bounded HTTP attempt path. This batch does not establish a hard
scheduling-latency bound during slow commands or unavailable authoritative
storage, nor does it replace the full deployment and regression gates.

### Automatic terminal-result recovery

Protected coordinator configuration can opt into automatic initiation of the
existing guarded recovery owner:

```yaml
slurm_terminal_recovery:
  enabled: true
  terminal_result_grace_seconds: 120
```

This selects execution schema 7. Existing deployments require the supported
stopped storage upgrade; opening a schema 6 database does not migrate it.
Set `enabled: false` to stop initiating new automatic recoveries while retaining
schema 7 and any already accepted recovery operations. Omitting the policy
preserves the previous deployment behavior and schema selection.

For a consumed execution grant with no report, exact terminal `sacct` evidence
starts a persisted grace period. Its accounting incarnation, assignment,
bootstrap incarnation and fence remain bound to the observation. Repeated
polls and coordinator restarts do not reset its first accepted time. Degraded
coordinator clock health prevents automatic initiation.

After the grace period, a task asks the submit agent to inspect its qualified
result directory through the bounded storage pool. The coordinator does not
assume that it can access the agent's mount. A missing result requires the
matching reservation binding; unavailable storage and invalid metadata are
distinct waiting reasons. The exact requested probe travels through the
existing durable evidence outbox, including lost-response replay.

Only a confirmed missing result initiates a stable guarded recovery operation.
The existing helper must still establish exact containment, the authority must
still match the attempt/fence, and capability revocation and interrupted-output
retention keep their existing owners. `COMPLETED` without a scientific result
does not mean scientific success. Automatic initiation requests failure and
does not request an automatic retry.

An ordinary result can supersede automatic recovery while containment remains
pending. Evidence-confirmed/closed recovery still fences subsequent ordinary
mutation. Explicit operator recovery retains its existing fencing semantics.
Jobs without a consumed execution grant remain outside this automatic path;
the policy does not invent an execution fence or containment evidence.

Waiting diagnostics distinguish the grace period, pending inspection,
unavailable/invalid/available results, unhealthy time and guarded recovery.
Source tests exercise restart during grace and pending containment, prestart
failure after grant consumption, late results, migration and result-directory
classification. These are source/protocol checks, not physical Slurm/GPU
qualification; the installed deployment must be upgraded and qualified separately.

### Reservation and credential IO

Embedded and outbound service compositions select asynchronous reservation,
script preparation, credential preparation and credential revocation using the
same bounded storage owner as result IO. Workers return verifier-only provider
receipts; only the agent owner records the submission intent, installs the
receipt and advances the evidence outbox. The retained operation/assignment
identity is rechecked when installing a returned receipt. Restart can replay a
provider's receipt created before its agent-journal installation. Direct
synchronous journal/protocol adapters remain available; they are not the
service deployment path.

Transport cleanup leaves its reservation directory and binding in place while
deleting payloads outside the quota lock. Its final bounded namespace update
and directory durability barrier run under that lock before capacity is
reused. A stalled deletion therefore still counts against the quota but does
not prevent another assignment from reserving spare capacity. A full quota
continues to produce assignment-specific backpressure.

Fault tests block reservation, credential creation or revocation while a peer
submits; reservation/creation tests also cancel that peer before releasing the
blocked worker. Other tests cover provider-receipt replay after restart and
quota accounting during blocked payload deletion.

### Scheduler command isolation

Persistent embedded and outbound services run external scheduler calls through
bounded continuations: one submission worker/slot, two observation/cancellation
workers with at most eight queued or running operations, and an independent
containment helper worker with at most eight outstanding calls. Journal reads,
state transitions, accounting validation and response publication stay on the
single agent owner. The synchronous public adapters advance those same journal
transitions directly. Command deadlines retain their existing configured meaning.

Submission capacity is acquired before claiming SUBMITTING. Restart discards
the in-memory continuation and reconciles the durable uncertain submission;
it never repeats sbatch because a reply was lost. A batch accounting snapshot
excludes competing transitions for its own assignments until its actual query
finishes. Other assignments and the submission slot continue independently.
Each helper request retains its exact captured proof; a superseded proof is
drained and discarded before a replacement starts. Closing an owner waits for
its actual commands and helpers, without declaring their effects absent.

A drain that fences an in-flight work poll now returns the exact typed fence
receipt. The service records sequence consumption and applies control on its
next turn, instead of reconnecting because of a generic protocol conflict.
Missing or conflicting poll identities still cannot authorize that transition.

Fault tests block sbatch, accounting or containment and require the same agent
to observe and cancel an independent assignment. They also assert that journal
transitions stay on the owner thread. Actual outbound service drain/restart and
embedded terminal-recovery checks cover the composed paths. No physical Slurm
qualification or live deployment upgrade is implied by these source tests.

The outbound bridge now advances HTTP acknowledgements independently, with two
HTTP workers, at most eight unfinished attempts and 32 transient exact-response
entries. Pending attempts deduplicate by session, epoch and exact evidence bytes;
task pagination does not change that identity. The durable outbox owns replay
after restart. Short-lived completed replies allow an assignment to finish its
current turn without repeating the same exchange. Fresh cancellation tasks take
precedence over a cached negative cancellation reply. Pending-storage replies
are never retained as completed effects.

Submission pauses at an explicit owner-thread authorization gate after its
durable SUBMITTING claim and before sbatch. An unfinished acknowledgement leaves
that gate retained; a fresh callback advances it on a later turn. It cannot
unwind the generator and accidentally authorize a second submission. Restart
still reconciles the retained uncertain submission through exact accounting.
Completed observations likewise survive an unfinished acknowledgement so they
can reach containment and release rather than continually starting new queries.

Embedded execution consumes completed assignment I/O before loading run contexts.
Containment helpers and scheduler commands retain submission-operation identities;
their completions resolve through the agent journal to the owning assignment.
Unchanged, authority-confirmed preparation projections do not repeat the original
preparation write transaction. Runs without project contracts record that absence
in their validated context and bypass per-stage action-reuse inspection; changed
retained documents invalidate that context through the existing byte-bound cache.

Recovery reconciliation scans up to 32 rows with a rotating identity cursor and
a cooperative quarter-second budget. Busy per-recovery guards are skipped, and a
failed recovery has its own paced retry. Assignment-fence queries select the exact
assignment in SQL rather than decoding the entire recovery population. The budget
does not interrupt an individual filesystem call. Slurm output chunk IO now
uses the separate bounded path described below.

### Input trust and preparation fairness

Read-only `input_directory` roots may select an explicit validation policy in
protected coordinator and execution-profile configuration. Omission (or
`input_validation: {policy: recursive}`) preserves recursive inspection.

```yaml
datasets:
  host_path: /site/datasets/formatted
  container_path: /loom/inputs/formatted
  access: ro
  qualification: {kind: input_directory}
  input_validation:
    policy: trusted_immutable_dataset
    version: publisher-version-1
    manifest:
      path: manifest.json
      sha256: "<sha256 of the selected existing manifest>"
    entry_points: [records, manifest.json]
```

The trusted policy verifies the exact protected root facts, the manifest digest,
every declared entry point and every selected location. It does not walk payload
directories. Manifest hashing streams chunks of at most one MiB with a 64 MiB
total bound; at most 256 explicit entry points are admitted. Relative paths
retain the existing no-escape/no-symbolic-link checks. The policy, version,
manifest and ordered entry points participate in portable root identity, so a
different policy/version cannot reuse another root's inspection evidence.

This is a publisher-immutability contract: changing payloads while retaining
the pinned manifest is not detected. Applications retain their semantic input
checks. The policy travels with shared root qualifications through preparation,
agent and compute/container decoding; it is not an output-publication setting.
Select it only with matching installed workers and existing publisher manifests.
Retained assignments preserve their originally admitted root identities.

Coordinator preparation tags CPU and GPU work and reserves one of its 32 owner
slots for each class. A class can hold at most 31 owners while the other class
can repeatedly prepare and dispatch. Completed prerequisites remain retained;
there is no eviction or CPU-job concurrency ceiling. The existing two preparation
workers and their actual in-flight ownership remain bounded. Slurm additionally
checks GPU-budget availability before starting new preparation, then rechecks
atomically when reserving the assignment. Already reserved operations bypass
this advisory preflight and retain their original replay path.


### Output transfer and transaction boundaries

New outbound agents may declare `slurm-pending-output-v1` alongside
`slurm-pending-effects-v1`. The coordinator advertises and checks this extension
before returning pending chunk acknowledgements. Existing registrations retain
their negotiated protocol; select the extension in protected registration and
principal policy during the supported upgrade. Embedded Slurm uses the same
finite output turns. Older agents retain their synchronous compatibility path.

At most eight assignments own a chunk future, sharing the existing two storage
workers and aggregate 32-operation bound with publication and retention.
Repeated exact requests observe the same future. Completed entries may be
reclaimed because persisted transfer offsets, verified staging/published bytes
and the sender's retained chunk own replay. A pending chunk never advances the
sender's offset, accepts scientific output, or authorizes cleanup. Status exposes
its process-local queued/running/received/failed state.

A stable advisory lock under the receiver's private `transfer-locks` directory
serializes each transfer across store instances and restarts. Filesystem writes,
fsync, checksums and publication occur outside SQLite write transactions. A short
transaction then rechecks incarnation, fence, descriptor and previous offset
before recording receipt. The lock files must not be unlinked while this receiver
is active. The deployment must support advisory locking on its selected storage.
A crash after append or rename but before receipt is recovered by exact replay;
whole-artifact checksums remain enforced for relayed payloads.

### Elapsed-time policies

The protected outbound agent declaration and bootstrap JSON accept an optional
policy (omission retains ten-second defaults):

```yaml
transport_policy:
  connect_timeout_seconds: 10
  response_timeout_seconds: 10
```

Both values must be finite, positive and at most 300 seconds. The response budget
covers the entire exchange, including connection setup. Socket deadlines and one
deadline monitor per occupied HTTP slot prevent trickled headers/body bytes from resetting
that budget. A resolver or TLS setup blocked in OS IO still occupies its bounded
worker; it cannot send after expiry. No unbounded replacement workers are created.
An expired exchange retains an uncertain result and its exact replay identity.
It does not terminate a workload or authorize another scheduler submission.

Startup persists its original wall-clock deadline across restart and converts
the remaining allowance, capped at the configured startup budget, into a
monotonic deadline for each invocation. Wall-clock changes cannot extend retries
within that invocation. Coordinator accepted-time checks still govern grants;
this local deadline is an abandonment policy, not execution authority.
Terminal-result grace and Slurm command deadlines remain separate settings.
Workload walltime remains a protected placement/profile setting and must include
startup and final publication as well as computation.

### Large readiness graphs and lifecycle observations

Run orchestration advances 32 authored stages per turn with a rotating stage
cursor, preserving their original ready-order values. Restart may rescan from the
head without repeating acknowledged preparation. Built-in work stores fetch the
run's preparation intents once per pass instead of opening a connection for every
projected stage. The public orchestrator's `max_work_items` and `after_stage`
parameters bound a pass; `next_stage` provides its next cursor.

Reservation and definitive decline update the stored stage record and its indexed
scheduling state in the same transaction. A declined assignment therefore returns
to the ready scan immediately. Local capacity offers include the observed
availability revision in their identity: a peer's claim or release during slow
input preparation cannot make a fresh offer conflict with an older offer for the
same stage. Reservation still checks the current offer and capacity before launch.

Preparation event reporting uses the exact native attempt receipt instead of
retaining two whole-run snapshots per stage. Native replay lookup selects its
exact event rather than decoding all prior events. Observer flushing alternates
its fact queues and yields after 32 facts or a cooperative 100 ms budget. One
slow callback may exceed that budget; later facts retain their original identity
for another turn. Observation remains best effort, with no new durable queue.
The 257-stage unavailable-Slurm/independent-resident regression passes with its
unchanged 45-second completion bound. This is source/fake-scheduler evidence,
not physical Slurm or GPU qualification.
