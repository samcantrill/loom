# Phase 15 Execution Plan: Management, CLI, And Examples

## Metadata

- Status: approved
- Roadmap stage and phase: Stage 29, Phase 15
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p15-management-cli-examples`
- Worktree root and path: `/home/can134/work/active/loom-worktrees/stage-29-p15-management-cli-examples`
- Base revision: `c4e3f6c` (`origin/develop` after Phase 14 merge metadata)
- PR target: `develop`
- PR title: `Stage 29 phase 15: complete management and examples`
- Dependencies: remotely merged Phase 14
- Workflow path: expanded; public CLI, concurrent IPC, and claimed example coverage
- Blockers: correction 1/3 fixed the initial management implementation. The
  required independent review then confirmed four reachable blockers: current-
  agent selection is ambiguous when replacement sessions share a timestamp;
  ready-stage SLURM operation IDs are absent from public operation detail/wait;
  public admission waits longer than the server slice return too early; and all
  three `validation: full` journeys overclaim the product surfaces they invoke.
  One bounded refiner correction (2/3) is in progress for this tight management-
  and-evidence cluster.

## Objective And Context

- Vertical outcome: operators can discover, wait for, and safely control exact
  admissions/agents/operations while unrelated writes and long polls cannot
  starve management; three runnable journeys truthfully demonstrate the complete
  supported local, remote, and ready-stage SLURM behavior and clean up all
  processes.
- Earlier dependency: Phase 14 supplies complete protected composition and
  restartable configuration revisions exposed by management detail.
- Later work explicitly out of scope: no later Stage 29 phase; completion
  requires the full correction audit and validation gate.

## Current Source And Harness

- `src/loom/queue/local_daemon.py` owns admissions, global revision triggers,
  accepted-time state, health, operations, and existing bounded status/detail.
- `src/loom/queue/local_daemon_transport.py` accepts and handles one Unix
  connection synchronously, including long admission waits.
- `src/loom/cli/queue.py` exposes submit/status/wait/cancel and guarded controls
  but not bounded admission/agent/operation discovery.
- `src/loom/queue/agent_sessions.py` owns agent/session/control views and
  principal-scoped recovery receipts.
- `docs/features/queue.md` and `examples/operations/managed-local-queue` document
  only one embedded happy path; its manifest overclaims full CLI/Python coverage.

## Scope

In scope:

- Admission-row semantic revision initialized deterministically and incremented
  only in the transaction that changes that admission's observable meaning.
- Targeted wait/detail based on that revision; unrelated/no-op writes do not
  wake a waiter.
- Bounded Unix worker pool with long-poll admission below total capacity,
  finite shutdown-aware server waits, and client-side renewal for
  longer/infinite waits.
- Bounded/cursored admission and agent list, targeted admission/agent detail,
  operation detail/wait, corresponding transport/client/CLI commands, and
  constant-shape status tokens including accepted-time revision/health.
- Portable protected local-owner operator rule resolved from verified socket or
  protected-config ownership while retaining mandatory action/agent/pool fences.
- Accepted-time expiry-owner fix, transient service-health clearing, and
  principal-bound time-recovery replay.
- Three example journeys and manifest/test validation of every claimed public
  surface, including Phase 13 clean shutdown and process leak checks.
- Necessary hard-cut protocol/schema/CLI version bumps and feature docs.

Out of scope:

- Unbounded scans, interactive dashboards, log streaming, remote shell access,
  weakening expected revision/session fences, automatic recovery, or real SLURM
  cluster dependency in default tests.

Assumptions:

- Existing cursor/page bounds remain the base for new list operations.
- Fake SLURM command gateways and generated local test CAs provide deterministic
  default-suite evidence without external services.
- Local-owner authorization applies only to owner-contained Unix operations,
  never remote TLS identities.

## Fixed Contracts And Private Discretion

- Observable behavior: a wait for admission A changes only when A changes or its
  timeout expires; status/control remain responsive during waits; CLI list/detail
  results are bounded and include the exact fences needed by subsequent guarded
  commands.
- Public/durable shapes: admissions own monotonic revisions; status
  includes coordinator/scheduling epochs and accepted-time health/revision;
  agent detail includes current session/config/inventory/availability revisions;
  operations expose typed state/result and bounded wait.
- Trust boundary: local-owner policy is configured explicitly and resolved to
  verified owner UID, then passed through the existing exact action/agent/pool
  authorizer. Recovery replay additionally matches principal subject.
- Cross-phase contracts: Phase 13 supervisor shutdown is the only example/test
  cleanup path; Phase 14 active configuration/scheduling epochs are displayed,
  not re-owned.
- Compatibility: affected daemon/transport/CLI identities hard cut; no legacy
  revision inference.
- Private choices: worker and reserved-management counts within documented safe
  bounds, condition/event implementation, exact command rendering, and example
  fixture organization.

## Proportionality

- Existing seam reused: bounded admission pages/details, agent-session views,
  typed operation receipts, Unix JSON request framing, CLI envelope, test TLS
  helpers, fake SLURM gateway, and example manifests.
- Additions correspond to current operator controls and documented deployment
  behaviors that otherwise cannot be discovered or exercised.
- Deferred: query language, server push, arbitrary concurrency configuration,
  UI, production CA automation, and real-site SLURM validation in default CI.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Admission revision changes iff that admission changes semantically | admission transaction | no-op/unrelated store mutation | spurious/missed wait | causal A/B/no-op tests |
| Long poll cannot monopolize management or shutdown | bounded Unix server, separate long-poll admission bound, and client loop | enough indefinite waits to fill the pool | status/control outage or leaked handler | saturated wait admission plus status/control/stop tests |
| Guarded controls remain discoverable and fenced | bounded agent/detail/operation projections | CLI operator | unusable or stale operation | discover-then-control matrix |
| Example claims equal invoked public surfaces | example manifest validator/e2e owner | docs/example edit | misleading supported behavior | manifest-to-test assertion and journey E2Es |

## Implementation Slices

1. Add per-admission revision ownership and migrate targeted detail/wait plus
   no-op/unrelated isolation tests.
2. Add bounded concurrent/shutdown-aware Unix handling, reserve at least one
   management worker from long-poll admission, and add client long-poll renewal;
   prove status/control concurrency and prompt stop under wait saturation.
3. Add bounded agent/operation reads through daemon, transports, clients, CLI,
   and docs; expose all mandatory guarded-control fences.
4. Resolve explicit local-owner operator policy and fix accepted-time,
   service-health, and principal-replay defects in their owners.
5. Replace the overclaimed example with managed-local-basic,
   managed-remote-operations, and managed-ready-stage-slurm journeys; enforce
   manifest claims and post-run supervisor/process cleanup.
6. Run the combined management/example gate and full Stage 29 completion audit.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- | --- |
| Package | required if exports change | typed read models | intentional cheap exports |
| Unit | required | revisions, codecs, parser, policy, bug fixes | A/B/no-op, bounds, replay principal |
| Contract | required for public application reads | structural client/service compatibility | dummy implementation and hard cut |
| Integration | required | concurrent IPC, reload/control discovery, health/time | real sockets and deterministic races |
| E2E | required | all three journeys and cleanup | CLI plus Python, subprocess TLS, fake SLURM, no PIDs |

Targeted commands:

    uv run --extra config pytest tests/unit/loom/queue tests/unit/loom/cli/test_queue.py
    uv run --extra config pytest tests/integration/queue tests/e2e/test_queue_cli.py
    uv run --extra config pytest tests/e2e -k 'managed_local_basic or managed_remote_operations or managed_ready_stage_slurm'

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: revision trigger duplication, worker-pool deadlock on shutdown,
  accidental unbounded projections, UID policy leaking into remote auth, or
  examples mocking away the public surfaces they claim.
- Review focus: causal revision semantics, bounded concurrency/shutdown, exact
  guarded-control data, and manifest-to-execution evidence.
- Stop if: a requested read cannot be bounded without a new product choice;
  socket-owner identity cannot be verified; or a default E2E needs an actual
  external SLURM/CA service rather than deterministic local infrastructure.
- Accepted debt: production site smoke tests remain opt-in; default suite proves
  command protocol and lifecycle with deterministic substitutes.

## Executor Handoff

- Read section range: this entire phase plan plus Stage 29 planning FR-39-44 and
  DD-38-40.
- Safe implementation slices: 1-6 above.
- Decisions not to revisit: per-admission semantic revision, bounded concurrent
  finite server waits, mandatory fences, explicit local-owner policy, three
  journeys, and truthful manifest claims.
- Conditions requiring manager action: unbounded API requirement, weakening a
  control fence, external-service dependency, compatibility/migration, or scope
  beyond Stage 29 correction.

## Workflow State

- Manager preparation: complete in the dedicated worktree at base `c4e3f6c`;
  current source and harness paths remain accurate
- Expanded planning: no phase-planner pass needed; the approved expanded design-
  safety and bounded plan-review findings already fixed supervisor epoch
  references, long-poll saturation, and Phase 14 CLI scope
- Implementation: complete at final reviewed tree `9c87de5`. The implementation
  owns per-admission revisions, bounded renewable waits, bounded agent and
  operation reads, verified local-owner scopes, accepted-time recovery fixes,
  and three executable management journeys.
- Refiner: complete. Correction 2/3 closed same-timestamp agent selection,
  accepted-time offer availability, execution-owned SLURM operation projection,
  and public wait renewal. Manager correction 3/3 then replaced all example
  shortcuts, completed FR-43 evidence, fixed remote shutdown, and made manifest
  claims exact.
- Pre-submit gate: passed. `make validate-pr` passed at source/test revision
  `76d770d`; the later documentation-only correction `9c87de5` passed all 29
  documentation/example checks and does not stale that receipt. A fresh
  `make test-summary` at `9c87de5` records 2,929 passes and 3 expected skips.
- Independent review: complete. Every blocker reported against `92c248c` is
  closed, including current-agent selection, ready-stage SLURM operations,
  truthful public-surface examples, accepted-time and service-health evidence,
  stale catalog IDs, and process cleanup. Final manager review found no blocker.
- Blocker corrections: 3/3 complete
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `src/loom/queue/local_daemon.py`, `local_daemon_transport.py`, `local_daemon_execution.py`, `agent_sessions.py`, `deployment.py`, and `slurm_ready_stage.py` own the lifecycle, bounded-read/wait, authorization, and SLURM projections. `src/loom/cli/queue.py` and intentional queue exports own CLI/public access. Three `examples/operations/managed-*` journeys, their exact manifests, and queue documentation own the supported examples. |
| Tests added or updated | Causal admission A/B/no-op revisions; saturated long-poll status/control/stop; bounded agent/detail/operation reads; same-timestamp replacement and expiry; local-owner and remote-credential negatives; accepted-time/service-health/replay; SLURM rejection/restart/result/release; exact manifest-to-invocation and PID cleanup. |
| Validated revision/tree state and evidence | Focused gates: 323 queue/CLI unit tests, 169 queue integration/E2E tests, 3 combined journey E2Es, 29 documentation/example checks, and the outbound reload lifecycle E2E passed. `make validate-pr` passed Ruff, zero-finding Pyright, 2,772 default tests, 157 configuration-extra tests with 3 expected skips, and both builds. Fresh `make test-summary` records 2,929 passed, 3 skipped, and zero failures/errors. |
| Validation-relevant changes after evidence | Only this workflow record changes after the fresh validation and summary evidence; no source, test, dependency, build, or validation configuration changed. |
| PR, review, and merge | Required independent review and manager review passed with no remaining blocker. PR creation and automatic squash merge remain manager-owned. |
| Residual risk and cleanup | No known phase blocker. Real site CA/prolog and production SLURM smoke validation remain intentionally opt-in; default validation uses generated localhost certificates and the deterministic fake scheduler gateway. Exact stale Phase 14 test supervisors were terminated; phase worktree/branch cleanup waits for merge. |
