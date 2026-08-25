# Phase 8A Execution Plan: Control And Cancellation Closure

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 29, Phase 8A
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p8a-agent-controls-cancellation-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-29-p8a-agent-controls-cancellation-closure`
- Base revision: clean `origin/develop` at
  `74e4b8354d82eb4fb727453ac6e4c9307b8fb3fb`
- PR target: `develop`
- PR title: `feat(scheduling): close agent controls and cancellation`
- Dependencies: Phase 7B merged as `d0da216`. Blocked Phase 8 candidate
  `db254bd`, metadata `378e577`, and closed PR #244 are read-only evidence, not
  a dependency base or supported schema.
- Workflow path: expanded because authorization, mutable component bindings,
  authority terminality, process containment, and external cancellation meet at
  irreversible boundaries. The approved findings and bounded architecture
  exploration make an additional phase-planner pass unnecessary. Independent
  implementation review remains required.
- Blockers: none; the maintainer approved this fresh, narrow recovery.

## Objective And Context

- Vertical outcome: merge Phase 8 controls/reload/cancellation only after every
  operator action is target-scoped, one complete coordinator component epoch is
  replaced without reinterpreting live work, and terminal cancellation is
  impossible while any prepared, local, remote, or SLURM owner remains live or
  unknown.
- Selectively reuse the validated Phase 8 source, tests, and feature docs from
  `db254bd`, excluding its roadmap metadata and all abandoned version identities.
- Phase 9 remains out of scope: no restart adoption, manual unknown-work close,
  session takeover, absence/timeout/PID inference, or retry after ambiguous
  execution.

## Current Source And Harness

- `local_daemon.py`, `agent_sessions.py`, their transports, and `cli/queue.py`
  own protected principals, role views, controls, durable intent, and status.
  Phase 8 proves most delivery/replay behavior but authorizes operators by role
  only.
- `LocalDaemonExecution._cancel()` composes authority, remote, and SLURM facts
  but omits local coordinator/journal and never-assigned preparation settlement.
  `SQLiteCoordinatorAssignments`, `SQLiteAgentJournal`, and the authority
  managed bindings already own the exact local states needed for the barrier.
- `ComponentRegistry` is the existing active/retained component owner.
  `ResolvedStagePlacement`/`StageWorkRecord` retain planner, hard-rule, and
  preference descriptors; managed decision receipts retain the policy and
  planner/provider descriptors. `SlurmReadyStageProfile` plus assignment and
  submission rows remain the separate profile-ID-keyed owner.
- Reuse the Phase 8 focused tests and existing queue/authority/package suites.
  Add causal cases for each review finding, not a Cartesian state matrix.

## Scope

In scope:

- Restore the Phase 8 drain, resume, trusted-local agent reload, coordinator
  scheduling reload, durable control delivery/ack replay, authority fences,
  contained cancellation, pre-`sbatch` suppression, exact-handle `scancel`,
  truthful status, CLI, and feature documentation.
- Give every protected operator rule an explicit finite action set and exact
  allowed agent/pool targets. `drain`, `resume`, `reload`, `cancel_active`, and
  `scheduling_reload` are distinct permissions. A control requesting
  `cancel_active` requires both its ordinary action and `cancel_active`.
  Authenticate and authorize before beginning or persisting an intent. HTTP,
  trusted direct composition, and owner-only Unix transport call the same
  authorizer; request content never supplies or widens scope. Missing scope is
  deny, not an implicit wildcard.
- Add one private `LocalDaemonExecution`-owned coordinator scheduling epoch:
  epoch identity, a frozen active/retained `ComponentRegistry` for resource
  planners, hard evaluators, preference scorers, and scheduling policy, plus the
  existing profile-ID/descriptor-keyed active/retained SLURM profile maps.
  Trusted configuration supplies a complete composition; built-ins are an
  explicit composition, not hidden constructor constants.
- Before reload mutation, build the complete replacement epoch and collect
  exact descriptor references from accepted nonterminal runtime placements,
  nonterminal stage work, capacity-holding managed assignments/decision
  receipts, and unreleased SLURM work. Serialize fresh admission with reload so
  a pre-reload accepted intent is retained and a post-reload stale intent is
  rejected before persistence. Resolve each retained descriptor to its existing
  exact object and reject before swap if any binding is missing, colliding, or
  reinterpreted. Fresh placement and scheduling use active bindings. Existing
  referenced work uses retained bindings, including when old- and new-epoch
  ready work coexist in one policy decision. Commit the durable epoch/receipt
  only after all fallible planning; the in-memory swap under the daemon cycle
  lock must then be non-fallible.
- Complete cancellation settlement across all owners. An effective authority
  epoch first fences prepare/bind/grant/start/retry. Reconcile never-assigned
  prepared attempts and never-ready descendants through an idempotent
  authority-owned cancellation operation. Scan local coordinator plus journal,
  remote assignments/controls, and SLURM assignments/submissions. Reserved or
  pre-grant work may unbind/release only with exact no-start proof; running work
  waits for current-fence result, containment, logical release, provider/profile
  release, and retained-output disposition. Any unknown owner fact keeps the
  admission `CANCELLING`.
- Make final `RunStatus.CANCELLED` an authority transaction/CAS that preserves a
  terminal success/failure winner, proves no live managed binding remains, and
  occurs only after the coordinator has observed all owner settlement. A sent
  control, disconnected agent, `scancel` success, missing event, or empty
  process-local handle map is never settlement evidence.
- Use fresh final identities: agent protocol v5, remote-agent journal schema 5,
  local-daemon control schema 5, and local-daemon CLI result v3. Reject current
  pre-cutover and abandoned Phase 8 candidate identities without mutation. No
  migration, upgrader, backfill, dual writer/reader, or compatibility codec.

Out of scope:

- New scheduler/resource semantics, generic component framework, remote config,
  distributed reload transaction, automatic route change, kill by unverified
  PID, Phase 9 recovery, or support for any Phase 8 candidate artifact.

## Fixed Contracts And Private Discretion

- Observable ordering is fixed:

  ```text
  authenticate + exact scope -> persist control -> withdraw availability
  cancellation intent -> authority epoch -> owner fan-out -> exact settlement
  all owners settled -> authority final cancellation CAS
  ```

- Reload is trusted-local and atomic at one owner. Durable records contain only
  inert descriptors/epoch IDs, never callables, configuration bodies, paths,
  commands, credentials, or secrets.
- Retention of exact same-version objects for live work is lifecycle safety, not
  backward compatibility. Old wire/store versions remain rejected.
- Table layout, private epoch class names, registry assembly helpers, lock
  placement beneath the daemon cycle lock, and safe diagnostic codes are
  executor discretion so long as one invariant has one owner.

## Proportionality

- Reuse the validated candidate and existing authority, coordinator, journal,
  registry, ready-stage, and transport owners. Add no parallel store or generic
  control service.
- Material additions are only the three independently demonstrated closures:
  scoped authorization, complete epoch composition, and complete cancellation
  settlement/finalization.
- Optional disaster recovery, wildcard/RBAC languages, live migration, and
  automatic garbage collection remain deferred.

## Invariant Ownership

| Invariant | Owner | Invalid boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Body target cannot widen operator authority | Protected principal policy authorizer | Direct/HTTP/Unix control admission | Unauthorized drain/reload/cancel | Cross-action, agent, and pool negative parity tests with zero intent mutation |
| Reload preserves every referenced implementation | Coordinator scheduling epoch plus existing durable descriptors | Trusted config replacement | Pending/live work reinterpreted or stranded | Old/new planner, rule, scorer, policy, and SLURM profile use around reload |
| Terminal cancellation follows all owner settlement | Authority final CAS plus coordinator settlement join | Local/remote/SLURM ambiguity | False terminality or resource collision | Prepared and local state barriers plus mixed-target cancellation |
| Candidate/old formats never execute | Strict decoders and fresh roots | Wire/store/CLI input | Accidental compatibility or ambiguous state | Previous and candidate-version rejection without mutation |

## Implementation Slices

1. Selectively restore Phase 8 source/tests/docs; assign fresh schema identities
   and prove old/candidate rejection.
2. Add protected operator scopes and common pre-persistence authorization with
   direct/HTTP/Unix negative parity.
3. Build the complete active/retained coordinator epoch and route fresh versus
   referenced work through its exact bindings.
4. Add local/prepared settlement and authority final-cancellation CAS; compose
   it with retained remote/SLURM fan-out and truthful status.
5. Close focused causal tests and operational hard-cut documentation.

## Test And Validation Plan

| Suite | Required | Behavior |
| --- | --- | --- |
| Unit | yes | Scope denial before mutation; complete epoch build/reject/swap; local prepared/reserved/bound/granted/running/unknown cancellation; strict versions |
| Contract | yes | Authority epoch/final CAS, terminal-winner preservation, Python/direct and HTTP authorization parity |
| Integration | yes | Trusted reload retaining exact old components; authority outage/replay; mixed local/remote/SLURM cancellation remains settling until each owner releases |
| E2E / opt-in | bounded | Local socket control/status hard cut; no real cluster or GPU dependency |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_local_daemon.py
    uv run pytest -q tests/unit/loom/pipeline/execution/test_managed_local.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py
    uv run pytest -q tests/unit/loom/pipeline/executors/slurm/test_ready_stage.py
    uv run pytest -q tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py
    uv run pytest -q tests/contracts/test_local_daemon_authority_contract.py tests/contracts/test_queue_python_api_contract.py tests/package/test_import_boundaries.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Review exact pre-persistence scope checks, descriptor reference collection,
  no-fail swap ordering, local same-process containment, unknown retention, and
  the final authority transaction. Green broad tests do not replace these cases.
- Stop if a live owner lacks an exact descriptor/assignment/fence/submission
  reference, if complete components cannot be supplied by trusted composition,
  or if terminal cancellation would require timeout/offline/PID inference.
- Accepted debt: genuinely unknown work remains `CANCELLING` until Phase 9
  obtains positive containment.

## Executor Handoff

- Read `AGENTS.md`, `.codex/workflows/roadmap-stage-implementation.md`,
  `.codex/prompts/phase-loop-management.md`, and this file from `Metadata`
  through `Risks, Review, And Stops`.
- Write only this Phase 8A worktree. Selectively reuse candidate `db254bd`
  source/tests/docs, never its roadmap metadata or version identities.
- Do not reopen accepted behavior, add compatibility, or implement Phase 9.
  Stop for the manager on any listed stop condition; do not delegate.

## Workflow State

- Manager preparation: complete on clean merged Phase 7B baseline
- Expanded planning: architecture boundary explored; no phase-planner pass
  needed because the approved three-finding recovery is decision-complete
- Implementation: initial executor packet in `0059d55`; manager correction
  `80b4655` closes the full component-epoch, exact retained SLURM dispatch and
  release, and terminal cancellation boundaries found during verification
- Refiner: one bounded pass used for the first qualified blocker; it stopped
  without changes, and the manager completed the concrete repair locally
- Pre-submit gate: passed on clean `80b4655`; `make validate-pr` and
  `make test-summary` completed successfully
- Independent review: required after PR
- Blocker corrections: 2/3 used; one bounded correction remains if independent
  review finds a product blocker
- PR and merge: PR #245 open against `develop`; CI and independent review pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `0059d55` restored the approved Phase 8 packet with fresh v5 agent/journal and daemon schemas plus v3 CLI result. `80b4655` adds exact action/target authorization, complete active/retained planner-rule-scorer-policy and SLURM epochs, serialized fresh admission/reload, mixed-epoch evaluation, canonical whole-plan cancellation, authority-owned finalization, and exact provider-release settlement. Feature behavior is current in `docs/features/queue.md`. |
| Tests added or updated | Phase 8 focused queue, managed-local, authority, SLURM, transport, production, CLI, contract, package, and scheduling-kernel coverage; causal cases cover denial before persistence, old/candidate v1–v4 rejection, retained accepted intents, stale fresh intents, old/new work in one decision, component/profile identity collision, exact retained-profile dispatch, provider-release retry, prepared and never-ready cancellation, live-binding refusal, terminal winners, and mixed owner settlement. |
| Validated revision/tree state and evidence | `80b4655` clean implementation tree: all focused suites passed; `make validate-pr` passed lint, type checking, the 2,534-test default suite, the 141-test configuration-extra suite with 3 skips, and package builds. [Test summary](../../../../build/test-summary.md) reports 2,675 passed, 0 failed, 0 errors, and 3 skipped across 2,678 selected tests. |
| Validation-relevant changes after evidence | None; this completion-record-only update is not validation-relevant. |
| PR, review, and merge | PR #245 is open, non-draft, mergeable, and targets `develop`; CI and the required independent review are pending. |
| Residual risk and cleanup | No implementation blocker. Unknown local, remote, or SLURM ownership remains `CANCELLING` until positive owner settlement; Phase 9 recovery remains out of scope. Worktree and branch retained for manager PR/review. |
