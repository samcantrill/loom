# Phase 9C Execution Plan: Remote Supervisor And Restart Closure

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 9C
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9c-remote-supervisor-restart-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path:
  `/home/can134/work/active/loom-worktrees/stage-29-p9c-remote-supervisor-restart-closure`
- Base revision: clean `origin/develop` at
  `44d06f329be6660fb12ab3ccc37cc443681733f2`
- PR target: `develop`
- PR title: `feat(scheduling): close remote managed restart`
- Dependencies: merged through Phase 8A. Blocked Phases 9, 9A, and 9B are
  selective read-only evidence, never dependency bases or supported schemas.
- Workflow path: expanded because a separate process owner and restart capacity
  interact. One executor and one independent implementation review are required.
- Blocker corrections: 3/3

## Objective And Context

Close one current consumer end to end: `LocalDaemonAgentHttpClient` executes its
existing resident remote assignments through one separately running durable
supervisor and can restart against the continuous supervisor without launching
a second root, losing a valid retained result, or publishing capacity before
every retained remote reference is reconciled.

This phase preserves the current non-empty multi-profile remote configuration.
It hard-cuts every old/single-profile supervisor root and removes the remote
client's in-memory `Popen` ownership. Phase 9D later reuses the merged private
service for embedded/local execution and performs the shared-workspace rename/
projection. Phase 9E/9F retain guarded recovery and replacement.

## Scope

In scope:

- Selectively restore the validated resident-worker service-injection hard cut
  and profile-set launch/schema evidence from blocked phases onto the fresh base.
- Derive one canonical complete `ResidentWorkerLaunchProfile` set from all
  `AgentTlsClientConfig.resident_profiles`; keep current multi-profile selection.
- Add an explicit remote agent-root initializer owned by
  `LocalDaemonAgentHttpClient` (or equivalent queue application composition)
  that requires the complete current config and creates journal/workspace plus
  protected supervisor state. Ordinary construction is open-only.
- Implement a separately running, separately locked, locally authenticated
  private supervisor service/client under `loom.queue`. The service reads the
  protected initialized configuration, continuously owns live process groups,
  and outlives any remote agent application instance.
- Persist the fully materialized exact launch before spawn, select one exact
  member of the bound profile set, and provide idempotent launch/query/stop.
- Prove positive complete process-group containment. Root exit, PID state,
  result-file presence, stop acknowledgement, endpoint loss, or timeout alone
  is never `CONTAINED`.
- Route the current `_RemoteAssignmentWorkspace` resident launch/query/control/
  result path through the supervisor client. Remove remote `_processes` and all
  direct `Popen`/wait/cancel ownership from `LocalDaemonAgentHttpClient`.
- Complete same-session remote restart at zero availability: reconstruct the
  complete retained remote delivery, execution-journal claim/profile, transfer,
  control, event, result/output, and outbox set; join exact supervisor receipts;
  replay normal remote operations; retain unknown work unavailable; publish one
  fresh complete provider observation before polling.
- Add service-before-remote-agent guidance and remote restart diagnostics.

Out of scope:

- Embedded/local `run_managed_local_assignment`, `LocalDaemonConfig` profile
  flags, shared-workspace renaming, and pipeline callable/thread owner removal;
  Phase 9D owns them after this service merges.
- SLURM recovery, privileged close/retry, different-session replacement, final
  operations, and final Stage 29 summary; Phases 9E/9F own them.
- Supervisor HA, PID adoption, timeout takeover, power fencing, migration,
  public supervisor protocol, or compatibility with any blocked root.

## Fixed Contracts

### Remote root and service composition

The current remote initialization entry point takes the complete
`AgentTlsClientConfig` (or its exact protected root/profile subset) and creates:

```text
agent root identity + remote journal + execution journal
+ assignment workspaces root
+ supervisor current configuration/profile-set identity
+ supervisor database + local authentication secret/verifier
+ private endpoint location
```

The initializer rejects an existing root. Ordinary
`LocalDaemonAgentHttpClient(config)` opens only exact current state and fails
with `managed_supervisor_state_requires_reinitialization` on absent, old,
corrupt, copied, or profile-set-mismatched state. It also requires the separately
running supervisor endpoint before session resume or capacity. The service, not
the agent application, holds the supervisor role lock and continuity epoch.

Private on-disk service configuration may persist the complete protected
profile paths/descriptors so a separately launched service can open exactly what
initialization authorized. Files are owner-only and canonical; the agent client
verifies the service-reported configuration fingerprint against its current
config. This is protected application state, not authored pipeline data or a
public plugin/config schema.

### Launch and evidence

The supervisor root binds stable `supervisor_id`, `agent_id`, current schema,
and the canonical complete allowed profile-set fingerprint. Every launch names
one exact profile ID/fingerprint and the complete identity:

```text
supervisor_id + continuity_epoch + agent_id + session_id
+ assignment_id + process_execution_id + execution_fence
+ launch_operation_id + canonical materialized launch-spec digest
```

The spec contains the current remote workspace, selected fixed resident-worker
argv/project/executable descriptor, and exact provider-derived environment.
Acceptance commits before one process group is created. Exact replay returns the
same receipt; any changed field conflicts. States are only `NOT_ACCEPTED`,
`STARTING`, `RUNNING`, `EXITED`, `CONTAINED`, or `UNKNOWN`.

The service owns descendant containment. `request_stop` is idempotent and only
acknowledges the request. The service may emit `CONTAINED` only after continuous
ownership plus bounded TERM/KILL escalation proves the complete process group
cannot execute or resume. Loss of service continuity converts every prior
nonterminal record to `UNKNOWN`; a new service never adopts by PID.

### Remote restart order

```text
exact continuous supervisor verified
  -> remote agent root/session lock acquired
  -> availability forced to zero; no poll/work request
  -> complete retained workspace/journal/reference set reconstructed
  -> exact supervisor receipts joined
  -> current coordinator session resumed
  -> events/results/outputs/transfers/outbox replayed and acknowledged
  -> providers released or unknown claims retained unavailable
  -> fresh complete provider/config observation published
  -> polling enabled
```

`NOT_ACCEPTED` submits only the already journaled launch operation.
`STARTING`/`RUNNING` resumes observation. `EXITED` retains its result while group
containment remains unresolved. `CONTAINED` plus matching result digest resumes
ordinary result/output import. `UNKNOWN` withholds claims and never relaunches.

## Invariant Ownership

| Invariant | Owner | Material consequence | Coverage |
| --- | --- | --- | --- |
| Complete remote profile set binds one root | Supervisor configuration | Wrong resident code after restart | One/many/reorder/add/remove/change profile tests |
| Agent restart does not restart the supervisor | Deployment/service composition | Lost ownership or duplicate launch | Real service plus two sequential agent processes |
| One accepted operation launches one root | Supervisor | Duplicate effects | Crash barriers and sentinel count |
| Only full group proof is contained | Supervisor | Unsafe release/takeover | Descendant/ignored-signal and weak-evidence negatives |
| Remote agent has no process owner | Queue remote composition | Restart loses live handle | Static owner removal plus causal restart tests |
| Capacity stays zero through reconciliation | Remote startup/provider owner | Double allocation | No-offer/no-poll barriers and unknown claim tests |

## Implementation Slices

1. Implement current remote root/profile-set initialization and the separate
   locked/authenticated service/client with materialized launch and containment.
2. Replace remote direct process ownership with supervisor launch/query/stop and
   preserve current workspace, transfer, control, result, and provider lifecycle.
3. Implement same-session zero-availability remote restart/replay, diagnostics,
   guidance, and causal multi-profile/fresh-process tests.

## Test And Validation Plan

- Unit: profile-set/config/service codecs, explicit-init/open-only, lock/auth,
  launch replay/conflict, materialized spec, states, containment escalation,
  schema/profile/copy/corruption rejection.
- Contract: remote workspace and agent execution use only supervisor receipts;
  `_processes`/direct `Popen` are absent from the application owner.
- Integration: real separate service plus fresh agent processes; select two
  profiles; crash before/after accept/spawn/result; descendant ignores TERM;
  agent restarts while worker runs; exact one-root sentinel; result/output replay;
  zero offer/poll until fresh provider observation; endpoint/continuity loss.
- Regression: current remote transfer replay, GPU environment, cancellation-
  before-start, session reload, Phase 5 authority restart, and import direction.
- Gate: focused supervisor/remote-workspace/agent-session tests, changed-path
  Ruff/Pyright, then `make validate-pr`. Phase 9F owns final summary.

## Risks, Review, And Stops

- Main risks are service implemented in-process, protected config mismatch not
  checked, a selected profile outside the bound set, endpoint/root exit treated
  as containment, retained `_processes`, or an offer before complete replay.
- Stop for a genuinely new public/durable choice, inability to prove full group
  containment, or inability of the existing remote workspace to use the fixed
  resident worker. Do not implement Phase 9D–9F.
- Independent review must verify service separation, containment, remote owner
  removal, multi-profile routing, and fresh-process restart.

## Executor Handoff

- Start from the fresh prepared Phase 9C branch and read this plan completely.
  Consult blocked Phase 9B only at `Complete launch-profile-set identity` and
  `Completion Record`; selectively reuse code, never its schema/history as base.
- Implement all three slices with real process barriers. Commit source/tests/
  phase-specific guidance; do not edit roadmap metadata or perform GitHub work.
- Do not implement embedded/local or later recovery behavior and do not delegate.
- Return one commit plus focused/full evidence, or one exact stop-condition
  blocker with the smallest remedy.

## Workflow State

- Manager preparation: complete on current `origin/develop`; dedicated worktree,
  finalized remote-only plan, and selective fresh foundation `718d3a5` recorded
- Implementation: complete. Executor correction 1 at `9794173` implemented the
  complete-profile-set root initializer, separately locked and authenticated
  supervisor service/client, materialized launch receipts, group-containment
  owner, remote-client cut-over, and zero-capacity restart barrier. Refiner
  correction 2 at `34012a4` added retained-reference replay, causal restart
  coverage, positive descendant containment, and explicit test-service teardown.
  Manager correction 3 at `8eb99d3` closed the remaining accepted crash barriers:
  exact `NOT_ACCEPTED` submission, accepted-start journal/coordinator joining,
  durable cancellation routing, provider-release/availability outbox replay, and
  one shared normal/restart result-output-release owner.
- Validation/review: manager validation complete at `d9cc0ae`; required
  independent review at `c240ec1` blocked the phase. A supported trusted reload
  can replace the resident launch-profile set without replacing its bound
  supervisor, so an advertised/granted new profile fails only at launch and
  leaves its claim unavailable. Required fresh-process restart and two-profile
  routing proof are also absent; the current restart matrix uses two client
  objects in one pytest process and the two-profile test proves binding only.
- PR/merge: no PR opened; correction 3/3 was already exhausted, so this branch
  is read-only blocked evidence for a fresh bounded closure

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and tests | Complete through `d9cc0ae` (`8eb99d3` behavior closure plus validation-fixture typing/runtime repairs). Changed-path Ruff and formatting passed; changed-source Pyright reported 0 errors; the affected supervisor, remote-session, and managed-journal suite passed, 38 tests. Its causal restart matrix covers crash before/after supervisor acceptance, before result commit, and after local availability publication but before coordinator release; every case retains one supervisor launch, replays release, and enables a fresh offer only afterward. Test teardown leaves no detached supervisor. |
| Validated revision and evidence | `d9cc0ae`; `make validate-pr` exited 0 on 2026-08-26. Repository Ruff and formatting, full Pyright (0 errors), the default test harness, the config-extra harness (141 passed, 3 skipped), and source/wheel builds passed. No detached Phase 9C supervisor process remained afterward. |
| PR, review, and merge | Required independent review blocked submission at `c240ec1`; no PR opened or merge attempted. |
| Residual risk and cleanup | Preserve this validated branch as read-only evidence. The smallest successor must reject any reload whose launch-profile-set fingerprint differs from the initialized supervisor, require fresh-root initialization, and prove the four restart barriers in fresh agent processes plus actual selection and launch routing for two bound profiles. No Phase 9D-9F behavior belongs in that closure. |
