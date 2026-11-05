# Coordinator responsiveness implementation

Worktree: `/nas/home/can134/work/loom-worktrees/coordinator-responsiveness`.
Branch: `codex/coordinator-responsiveness`, based on `develop` at `19f6a5e5`, with `b8db3e6b` integrated before landing.
This is a focused maintenance change, not a numbered roadmap stage.

## Accepted scope

Slow reconciliation must not block healthy offer renewals, bounded work polls,
status, or recording cancellation. Preparation is disposable; durable admission,
reservation, binding, grant, release, replay and recovery records remain the
execution authority. Offer expiry never releases running ownership. Session
replacement, cancellation and scheduling changes fence incompatible prepared
work. Keep the existing 30-second offer lifetime.

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

Deployment remains blocked. The supported retained-result upgrade preview refused
with `source agent unavailable: calypso`. Read-only native evidence also shows
six pending preparations outside its recovery cohort. The two outstanding remote
assignments on Shazza and Fenix have successful agent-local durable results, but
those results do not belong to the six pending preparation children. The existing
recovery contract intentionally rejects this state. No upgrade apply, forced
restart, database mutation, cancellation or replacement submission was performed.
The fleet still selects release `loom-19f6a5e50e24`.

Preserve and resume these exact retained operations once the supported upgrade
conditions are met:

- `omit-windowed-mmpd-20261105-c55e5a1c2`
- `omit-windowed-pure-intra-test-20261105-c55e5a1c2`

Both remain pending with their original preparation admissions and submission
records. A broader recovery path for pending preparations requires an explicit
contract decision; this responsiveness change does not silently widen it.
