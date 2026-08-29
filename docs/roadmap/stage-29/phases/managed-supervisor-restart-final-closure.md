# Phase 9B Execution Plan: Managed Supervisor And Restart Final Closure

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 9B
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9b-managed-supervisor-restart-final-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path:
  `/home/can134/work/active/loom-worktrees/stage-29-p9b-managed-supervisor-restart-final-closure`
- Base revision: clean `origin/develop` at
  `44d06f329be6660fb12ab3ccc37cc443681733f2`
- PR target: `develop`
- PR title: `feat(scheduling): close managed restart supervision`
- Dependencies: Phases 1–3D, 4A, 5A, 6, 7B, and 8A merged. Blocked
  Phases 9 and 9A are read-only evidence, not dependency bases or supported
  schemas. Manager selectively restored only source/test foundation commits
  `ea6e06c` and `24b8c9c` as fresh-branch commit `264ac1f`.
- Workflow path: expanded because a separately running process owner, positive
  descendant containment, and restart capacity causally interact. One executor
  and one independent implementation review are required.
- Blockers: correction 3/3 ended without source changes because the remaining
  separate-service, two-path routing, and restart cluster could not be completed
  within the bounded repair. Correction 1/3 commit `2fdfcf8` remains validated
  selective evidence only; the supervisor is still in-process and no production
  path or restart outcome is closed. Fresh Phase 9C owns the remote supervisor/
  restart vertical. Fresh Phase 9D then owns embedded/local bundle cut-over and
  restart, including the already-decided explicit CLI profile flags.
  Correction 1/3 implemented the required local field and schema-v2 canonical
  complete profile-set identity as `2fdfcf8`. Correction 2/3 found that daemon
  CLI construction had no explicit source for that required value. The fixed
  flag-only hard cut below resolves it without a second config-file schema,
  inference, or compatibility default. The same refiner receives one directly
  related final repair for the remaining finalized implementation.
- Blocker corrections: 3/3 exhausted

## Objective And Context

Deliver the unchanged managed half of the accepted Phase 9 recovery outcome:
both embedded/local and remote HTTP agents use one separately running durable
supervisor and one resident assignment bundle. Restarting the agent application
must reconnect to the continuous supervisor, reconcile every retained fact at
zero availability, replay a valid result, and never start a second root or reuse
capacity around unknown work.

Phase 9A proved two missing decisions before implementation. Its shared private
bundle decision is retained. Its one-profile supervisor identity is corrected
here to bind the complete configured profile set while each launch selects one
exact member. This preserves the current supported multi-profile remote agent;
it does not support any old root, schema, inferred profile, or migration.

Phase 9E owns coordinator/SLURM restart, guarded recovery close, and existing-
policy retry. Phase 9F owns different-session replacement, remaining operations,
and final Stage 29 validation.

## Scope

In scope:

- Require one protected `ResidentWorkerLaunchProfile` in `LocalDaemonConfig`.
  Preserve the existing non-empty tuple of `ResidentExecutionProfile` values in
  `AgentTlsClientConfig`; derive its complete launch-profile set.
- Implement one current supervisor configuration identity over `agent_id` and
  the canonical complete allowed launch-profile set. A launch selects one exact
  configured profile ID/fingerprint and includes it in the launch digest.
- Implement one separately running, separately locked, locally authenticated
  queue-owned supervisor service/client. Fresh agent-root initialization creates
  the current supervisor root; ordinary service/agent start is open-only.
- Persist the fully materialized launch specification and complete identity
  before spawn. Exact operation replay is idempotent; any changed field
  conflicts. The one continuous supervisor is the sole process owner.
- Use a complete exact child environment, never ambient supervisor environment.
- Report only `NOT_ACCEPTED`, `STARTING`, `RUNNING`, `EXITED`, `CONTAINED`, or
  `UNKNOWN`. Prove `CONTAINED` only after the continuous supervisor establishes
  that the complete process group cannot execute or resume.
- Generalize the Phase 9A-fixed resident bundle/workspace from the current
  remote delivery shape. Stage and verify every immutable input before launch;
  construct the child request only from assignment-local paths; retain and
  digest-check result/output bytes for replay.
- Route embedded/local and remote production managed execution through the same
  workspace and supervisor client. Remove `_ManagedWorkerHandle`, journal
  `_process_handles`, remote `_processes`, optional managed executor/artifact-
  store/plugin/validator/process-launcher hooks, and all alternate lifecycle
  owners. Pipeline execution never imports queue.
- Hard-cut agent journal, workspace, supervisor, and protected configuration
  identities. Old, missing, corrupt, copied, single-profile, or mismatched state
  fails before session resume, work polling, or capacity offer with
  `managed_supervisor_state_requires_reinitialization`.
- Complete same-session restart for both paths: lock owner state; publish zero
  availability; reconstruct complete retained assignment/claim/profile/event/
  result/output/outbox references; join exact supervisor receipts; replay normal
  results/releases; retain unknown work unavailable; then record and publish one
  fresh full provider observation.
- Preserve Phase 5 coordinator/authority restart and exact execution fences.
- Add supervisor-before-agent service guidance and focused diagnostics.

Out of scope:

- SLURM restart/containment, manual recovery close, retry choice, different-
  session replacement, final broad recovery CLI/status, and final Stage 29
  E2E/summary; Phases 9E/9F own them.
- Supervisor HA, process adoption, timeout takeover, power fencing, checkpoint
  migration, a public supervisor/plugin protocol, or legacy compatibility.

## Fixed Contracts

### Complete launch-profile-set identity

The supervisor configuration is one exact protected value conceptually shaped
as follows; private names may differ:

```python
@dataclass(frozen=True)
class SupervisorLaunchConfiguration:
    agent_id: str
    profiles: tuple[ResidentWorkerLaunchProfile, ...]  # sorted by profile_id

    @property
    def fingerprint(self) -> str:
        return digest({
            "agent_id": self.agent_id,
            "profiles": [
                {"profile_id": profile.profile_id,
                 "fingerprint": profile.fingerprint}
                for profile in self.profiles
            ],
        })
```

Every profile descriptor is the exact plain-data encoding of the existing
`ResidentProfileDescriptor`; its `profile_id` is the selection key. IDs and
fingerprints are unique and the set is non-empty. Local composition supplies a
one-member set from its required launch profile. Remote composition supplies the
canonical complete set derived from all configured `resident_profiles`.

Fresh initialization persists the current schema identity, stable
`supervisor_id`, `agent_id`, and complete configuration fingerprint. The service
opens only when the configured complete set matches. Adding, removing, or
changing a profile requires fresh initialization; an old single-profile root is
not upgraded. This is a hard cut of protected state, not a contraction of the
current multi-profile public configuration.

`ResidentWorkerLaunchProfile` is an intentional lazy public export from
`loom.queue` because `LocalDaemonConfig` now requires callers to construct it;
the supervisor service/client remain private. Both `queue daemon-init` and
`queue daemon-serve` require this exact flag group:

```text
--resident-project-root PATH
--resident-python-executable PATH
--resident-profile-id ID
--resident-profile-revision REVISION
--resident-project-fingerprint FINGERPRINT
--resident-environment-fingerprint FINGERPRINT
--resident-executor-fingerprint FINGERPRINT
```

The CLI constructs `ResidentProfileDescriptor` from the five descriptor fields,
then constructs `ResidentWorkerLaunchProfile` from its exact `to_dict()` plus
the two paths. All seven flags are required on both commands. There is no JSON/
YAML profile file, environment-variable fallback, current-directory or
`sys.executable` inference, legacy option alias, or default descriptor. Update
the local-daemon CLI envelope identity from v3 to v4 for this hard cut. Tests and
operational examples must pass the explicit current values.

Each launch carries selected `profile_id` and profile fingerprint plus:

```text
supervisor_id + supervisor_continuity_epoch
+ agent_id + session_id
+ assignment_id + process_execution_id + execution_fence
+ launch_operation_id + canonical_launch_spec_digest
```

The selected member must exist exactly in the bound set. The persisted launch
spec includes the full bundle/workspace identity, selected executable/project
root descriptor identity, exact environment, and fixed resident-worker argv.
It never stores only a digest in place of the materialized specification.

### Shared resident assignment bundle

The authoritative detailed bundle contract is the blocked Phase 9A plan's
`Fixed shared resident-assignment bundle decision`. It generalizes the existing
remote semantic request and workspace into one current queue-private schema:

```python
bundle = ResidentAssignmentBundle(
    assignment_id=assignment.assignment_id,
    profile=selected_profile_descriptor,
    stage_request=path_free_prepared_stage_data,
    inputs=verified_assignment_local_manifests,
    claims=exact_claims,
    provider_descriptors=exact_provider_descriptors,
)
```

For embedded execution the parent alone reads the existing run store and source
artifact bytes. It copies bounded no-follow regular files into the workspace and
maps the verified retained child result back to the original journal-owned run
identity before using the ordinary finalization path. The child and supervisor
never receive `LegacyRunStore`, arbitrary Python services, authored commands, or
credentials. Remote delivery performs the same projection through its existing
bounded transfer protocol. There is no compatibility alias or second bundle.

### Supervisor service and containment

The supervisor service, not the agent application, holds the supervisor lock,
endpoint, live process objects, process groups, and continuity epoch. The agent
client authenticates over a protected local endpoint and sends only bounded
canonical launch/query/stop messages. Service or endpoint loss is `UNKNOWN`, not
proof that a retained process stopped.

Acceptance is durable before spawning exactly one new session/process group.
`request_stop` acknowledgement means requested only. `EXITED` means the root
exited and may carry a result digest, but descendants may remain. `CONTAINED`
requires positive group nonexistence after bounded TERM/KILL handling and exact
continuous ownership. PID absence/presence, root exit, a result file, timeout,
or endpoint failure alone never qualifies.

### Same-session restart order

```text
matching supervisor service/configuration verified
  -> agent role lock acquired
  -> current journal/workspace identities opened
  -> zero availability and no poll/work request
  -> complete retained reference set reconstructed
  -> exact supervisor receipts joined
  -> current session resumed
  -> events/results/outputs/outbox replayed and acknowledged
  -> physical claims released or retained unavailable
  -> fresh complete provider observation recorded and published
  -> polling enabled
```

`NOT_ACCEPTED` may submit only the already journaled launch operation.
`STARTING`/`RUNNING` resume observation without launch. `EXITED` withholds the
claim until containment and valid result handling. `CONTAINED` with a matching
result imports through normal journal/authority flow. `UNKNOWN` or any mismatch
keeps the claim unavailable and never launches or releases around it.

## Invariant Ownership

| Invariant | Owner | Material consequence | Required evidence |
| --- | --- | --- | --- |
| Complete allowed profile set is stable | Supervisor root/config fingerprint | Wrong code executes after reload/restart | One/many/reorder/add/remove/change profile tests |
| One exact launch creates at most one root | Supervisor | Duplicate stage effects | Crash barriers before/after accept/spawn and exact replay/conflict |
| Agent restart is not supervisor restart | Service composition | Lost containment evidence | Real service + fresh agent process while worker runs |
| Contained means complete group cannot resume | Supervisor | Unsafe close/capacity reuse | Descendant and ignored-signal tests; endpoint/root-exit negatives |
| Both managed paths share one bundle/process owner | Queue composition | Divergent restart behavior | Local/remote contract parity and old-owner absence tests |
| Restart publishes zero until complete reconciliation | Agent startup | Double allocation | Offer/poll barriers and retained unknown claims |
| Verified result uses ordinary finalization | Journal/coordinator/authority | Stale/lost output mutation | Result-before-journal and output/outbox replay tests |

## Implementation Slices

1. Replace the foundation's single-profile database object with the current
   complete-set configuration, explicit-init/open-only root, locked/authenticated
   separate service/client, materialized launch codec, and positive containment.
2. Generalize the resident bundle/workspace, add exact embedded projection and
   retained-result import, route both production paths through the client, and
   remove all obsolete in-memory process owners and callable hooks.
3. Implement same-session zero-availability reconciliation/replay in both
   compositions, hard-cut state/config checks, diagnostics/guidance, and Phase 5
   restart regressions.

## Test And Validation Plan

- Unit: profile-set canonicalization, one/many/reorder replay, add/remove/change
  rejection, bundle/launch full codec, endpoint auth/lock, bounded states,
  schema/copy/corruption rejection, containment negatives and escalation.
- Contract: local and remote paths expose identical bundle and supervisor
  launch/query/stop/result semantics; neither old process owner or callable path
  remains; pipeline imports no queue.
- Integration: real separate supervisor and fresh agent processes at crash
  boundaries; multiple profiles selected sequentially/concurrently; descendant
  ignores TERM; agent restarts while work runs; result file precedes journal;
  exact replay produces one sentinel; unknown work suppresses capacity.
- Regression: Phase 5 coordinator/authority restart, remote transfer replay,
  GPU environment, cancellation-before-start, and current multi-profile routing.
- Commands: focused supervisor/bundle/managed-local/agent-session/local-daemon/
  package-import suites; changed-path Ruff/Pyright; then `make validate-pr`.
  Phase 9F owns the final fresh `make test-summary`.

## Risks, Review, And Stops

- Main risks are a set fingerprint that ignores order/content, selection outside
  the bound set, an in-process supervisor masquerading as a service, launch spec
  persistence containing only a digest, root exit treated as containment, a
  retained old process owner, or early capacity publication.
- Stop for a genuinely new public/durable choice, inability to prove complete
  process-group containment, or a supported managed path that cannot use the
  fixed resident bundle. Do not stop for Phase 9E/9F work.
- Independent review must verify profile-set identity, continuous ownership,
  positive containment, both production paths, and zero-availability restart.

## Executor Handoff

- Work only from the prepared fresh branch/worktree. Read this file completely,
  blocked Phase 9A headings `Fixed shared resident-assignment bundle decision`
  and `Completion Record`, and selectively reused foundation source/tests.
- Implement all three slices. Replace the foundation's single-profile schema;
  do not adapt it, add migration, or retain compatibility aliases.
- Use real service/agent/worker process barriers. Mock state flags do not prove
  service continuity, no-repeat launch, or group containment.
- Commit source/tests/phase-specific guidance. Do not edit roadmap metadata,
  perform GitHub operations, implement Phase 9E/9F, or delegate.
- Return a commit ID and concise focused/full validation evidence, or one new
  stop-condition blocker with the smallest remedy.

## Workflow State

- Manager preparation: complete on current `origin/develop`; dedicated worktree,
  final plan, and selective foundation commit `264ac1f` recorded
- Implementation: profile-set foundation `2fdfcf8` committed and manager-
  verified; separate service, production paths, constructor cut-over, and
  restart reconciliation remain
- Refiner: first turn stopped without changes on the missing daemon CLI
  representation; manager fixed the required flag-only v4 hard cut. Its one
  directly related final turn made no changes and did not complete the remaining
  service/path/restart cluster
- Pre-submit gate: not reached
- Independent review: required
- PR and merge: no PR; blocked read-only evidence. Fresh Phases 9C/9D split the
  unchanged managed outcome by current remote and embedded/local consumers

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `2fdfcf8` requires `LocalDaemonConfig.resident_worker_launch_profile`, binds explicit local initialization, persists schema-v2 complete profile-set identity and materialized launch JSON, and exposes the remote canonical set. Service/path/restart slices remain. |
| Tests added or updated | Profile-set canonical reopen/change rejection and required local config coverage added; broader constructors and causal integration pending. |
| Validated revision/tree state and evidence | Manager at `2fdfcf8`: changed-path Ruff passed; Pyright 0 findings; focused supervisor/local-daemon suite 35 passed. |
| PR, review, and merge | No PR opened; correction 3/3 exhausted. |
| Residual risk and cleanup | Supervisor remains in-process, both production paths retain old owners, and restart is absent. Branch/worktree remain read-only; Phase 9C owns remote closure and Phase 9D owns embedded/local closure. |
