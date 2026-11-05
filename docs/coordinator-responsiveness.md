# Coordinator responsiveness implementation

Worktree: `/nas/home/can134/work/loom-worktrees/coordinator-responsiveness`.
Branch: `codex/coordinator-responsiveness`, based on `develop` at `19f6a5e5`.
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

## Current evidence and remaining work

Startup: develop is clean; original `/nas/home/can134/work/loom` contains unrelated
changes and is preserved. Implementation is in progress; nothing has merged or
been deployed. Independent implementation review is pending.

Implemented and locally checked:

- Real retained-context IO reproducer: original renewal and poll operations
  timed out while the loader was blocked. Cancellation already recorded intent.
- Two-slot context preparation, no queued backlog, fair admission rotation,
  completion-only consumption, revision/epoch rejection, disposable shutdown.
- Separate reconciliation guard, extracted read-only loader and explicit prepared
  intent handoff. Durable authority binding still uses its retained identity.
- State-lock wait/hold diagnostics defer nested reporting until lock release.
- Admission-filtered stage-work query and eligibility refresh, with both store
  variants and SQLite filtering before decoding covered.

Evidence on the initial implementation tree: 89 responsiveness/agent-session
checks passed (the then-current four new cases plus all 85 session cases);
28 orchestration checks passed; 16 selected responsiveness/production-daemon
checks passed after adding stale-preparation and saturation coverage. The latter
selection includes backoff, unhealthy-peer isolation, pending cancellation,
independent runs, global priority and restart joining retained supervised work.
Commands and disposable output are under `/tmp/loom-coordinator-responsiveness`.
Changed-file Ruff and Pyright passed (zero errors/warnings); `git diff --check`
passed.

Remaining implementation is substantial: remove the remaining broad state-lock
sections around owner observation, authority, action verification and scheduling;
retain short conditional transitions and lock ordering for renewal/publication,
replacement/reload and start permits. Add all remaining timing boundaries and
transport capacity protection. Implement captured-byte context caching and bound
repeated background preparation rate as well as concurrent capacity. Complete
ownership/race/recovery coverage, five-agent qualification and live retained-state
upgrade/resumption, then independent review and merge. The passing context-loader
reproducer alone does not establish responsiveness of other slow dependencies.
