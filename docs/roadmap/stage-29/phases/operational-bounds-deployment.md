# Phase 12 Execution Plan: Operational Bounds And Deployment

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 12
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p12-operational-bounds-deployment`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; phase path is `<root>/stage-29-p12-operational-bounds-deployment`
- Base revision: `4f2e155d975009bc7a33f814db2034832e6592c2`
- PR target: `develop`
- PR title: `feat(queue): bound daemon operations and deployment`
- Dependencies: remotely merged Phase 11
- Workflow path: fast; public and durable shapes are fixed by the correction
- Blockers: none. The merged Stage 33 Discord coordinator reporter is an
  explicit optional history consumer: it will traverse bounded admission pages
  and targeted owner-detail operations while preserving its exact aggregate and
  active-run observable contract. Each core operation and response remains
  bounded; the scheduler and summary path never perform that traversal

## Objective And Context

- Vertical outcome: where a site permits persistent role processes, the
  corrected scheduler runs behind bounded internal/public queries, constant-size
  poll replay, scoped reconciliation and clock health, all-or-nothing fresh
  initialization, and supported coordinator plus agent service commands
  constructed from protected configuration.
- Earlier dependency: Phase 10 provides global assignment scheduling and
  per-admission reconciliation facts; Phase 11 provides exact coordinator/agent
  composition and profile/provider identity.
- Later work explicitly out of scope: module splitting except around the new
  owner/query/service seams; the phase completes the requested correction.

## Current Source And Harness

- Relevant files and symbols: `LocalDaemonStatus`, `LocalDaemon.status`,
  `LocalDaemon.reconcile_once`, `LocalDaemonSocketServer/Client`, CLI daemon
  handlers/configuration, agent poll request/storage in `agent_sessions.py`,
  `_accepted_time`, `_initialize_root`, `LocalDaemon.initialize`, and existing
  remote agent session transport/service harnesses.
- Existing tests and seams: daemon socket/CLI tests; large owner-status joins;
  poll replay/principal isolation tests; regression clock test; fresh-root schema
  tests; real subprocess supervisor and outbound agent session integration.
- Import, dependency, or harness constraints: public reads call small application
  operations; internal reconciliation uses store-owned nonterminal queries;
  transport derives principals and owns no state/policy; CLI/deployment wiring
  owns no scheduling decisions.

## Scope

In scope:

- Replace the full `status()` payload with a small `DaemonStatus` summary:
  health/diagnostic, active and waiting admission counts, running assignment
  count, coordinator/scheduling epoch, accepted-time health, and bounded stable
  metadata only. Summary construction must not enumerate/join detailed history.
- Add `admissions(limit=100, cursor=None)` with limits 1..100, ordered by durable
  `(enqueue_sequence, admission_id)` and an opaque keyset cursor naming the last
  returned pair. The result contains records plus a next cursor or null; inserts
  after the cursor cannot reorder earlier pages. Add targeted
  `admission(admission_id)` detailed owner join with a typed not-found result.
  Add targeted `wait(admission_id, expected_revision, timeout)` returning
  `CHANGED`, `TERMINAL`, or `TIMEOUT` plus the current admission/revision. A
  lower expected revision returns immediately, an equal revision waits, a
  greater revision conflicts, and a missing admission is typed not-found. A
  queue item is resolved once to its admission before entering this operation.
  Socket/direct/CLI surfaces call these operations; wait never polls full status.
- Adapt the merged Stage 33 Discord sidecar to consume those bounded pages and
  targeted owner details. It retains exact admission and authority-state counts,
  active-run stage progress, message limits, and its existing public reporter
  behavior. The optional sidecar owns traversal and any stable terminal-detail
  cache; core queue operations gain no Discord-specific query or enlarged
  summary payload.
- Make internal reconciliation read only active/nonterminal admissions and
  assignments through small store queries. Detailed terminal history loads only
  on an explicit targeted read.
- Replace unbounded `agent_polls` history with one replayable sequenced state per
  session/principal. The exact current sequence and digest replays the stored
  result; current+1 advances; older raises typed stale-poll; a gap raises typed
  sequence-gap. Agent-local state uses the same monotonic contract. Bump the
  agent-session/poll protocol and root schema, reject old rows/roots, and prove
  constant row count.
- Query the Phase 10 reconciliation-health store and expose aggregate service
  health as degraded while any unresolved admission failure exists. Phase 10 is
  the sole durable owner and its same-admission success is the only ordinary
  clear operation. Phase 12 adds no second health table or mutation semantics.
  Deterministic incompatibility blocks only its admission; shared coordinator/
  store outage remains global.
- Persist explicit accepted-time state with high-water, health, diagnostic, and
  revision. Reject both regression and a protected-policy maximum forward step
  before changing high-water. A time anomaly pauses new scheduling while
  retaining existing work and exposes a stable diagnostic. Recovery is one
  operator-authorized, operation-ID/digest replayable `TimeRecoveryRequest`
  containing the expected time revision, expected coordinator epoch, and reason.
  The daemon samples its own clock; recovery requires the named degraded revision
  and current epoch plus `now >= high_water`. It atomically accepts `now` as the
  new high-water, marks time healthy, increments the time revision, rotates the
  coordinator epoch, and withholds all earlier-epoch offers until fresh offers
  arrive. Exact replay returns the same receipt; a changed digest, revision, or
  epoch conflicts. A still-regressed clock cannot be recovered by assertion.
- Make initialization filesystem-atomic at each supported publication unit. The
  local coordinator command accepts one absent deployment root, constructs and
  validates its coordinator and embedded-agent subroots plus a stable-ID binding
  manifest inside one sibling staging directory, then renames that single bundle
  into place. The outbound-agent command independently constructs and renames one
  absent agent root. Startup accepts only a complete bundle/role root with its
  final binding marker. A crash before rename leaves no requested target; a crash
  after rename leaves a complete valid unit. Existing targets remain rejected and
  untouched; arbitrary coordinator/embedded-agent roots on separate filesystems
  are no longer a supported initialization shape.
- Add one supported protected coordinator configuration file shape and a
  coordinator service command. Add a distinct outbound agent service command
  using its protected root, profiles, providers, endpoint/trust policy, and
  reconnect loop. Both compose the Phase 11 exact identities/providers and the
  same application protocol; no second embedded-only behavior path. These are
  foreground role applications, not a requirement to daemonize on an HPC login
  node or an assertion that every site permits such a host.
- The exact approved command surface is `loom queue daemon-init CONFIG` and
  `loom queue daemon-serve CONFIG` for the coordinator bundle, plus
  `loom queue agent-init CONFIG` and `loom queue agent-serve CONFIG` for the
  outbound agent. `CONFIG` is one explicit-path, owner-protected, versioned YAML
  document loaded through Loom's existing trusted configuration machinery and
  resolving to the corresponding typed coordinator-service or outbound-agent-
  service configuration. Initialization and serving consume the same document
  so root bindings and composition fingerprints are revalidated. There is no
  implicit discovery or environment override. The former setup root/profile
  flags are removed without compatibility; existing daemon client/operation
  command names remain unchanged.
- Update feature, CLI, testing, deployment/recovery guidance and final examples
  for the new schemas, upgrade procedure, endpoints, and service commands. The
  deployment matrix must distinguish this persistent managed mode from the
  historical service-less whole-run SLURM queue/single-job/`afterok` modes and
  state that Stage 29 ready-stage SLURM requires the coordinator endpoint while
  its bootstrap is active.

Out of scope:

- Web dashboards, arbitrary history search, offset pagination, server-side
  streaming frameworks, coordinator HA, migrations, or automatic time healing.
- New hosted services/dependencies, generic secret management, daemonization
  frameworks, systemd packaging, or production PKI automation.
- Service-less many-run admission, whole-run SLURM driving/reconciliation,
  dynamic intermittent coordination, remote query gateways, artifact/log
  relay, or compute-originated reporting; Stage 32 owns the accepted first two
  items and defers the rest.

Assumptions:

- Local Unix transport remains a supported protected coordinator transport;
  existing authenticated agent transport supplies the remote service boundary.
- A site using these managed role commands provides a permitted stable service
  host. A site that forbids one uses the separate whole-run delegated SLURM path;
  Phase 12 does not place a coordinator on a prohibited login node.
- Configuration is trusted site code/data and may reference private key/cert
  paths; public status must never expose those paths or values.

## Fixed Contracts And Private Discretion

- Observable behavior: summary size does not grow with terminal runs; admissions
  paginate deterministically; targeted wait observes one revision; poll storage
  remains constant; one failed admission stays degraded despite another success;
  a forward clock jump pauses scheduling without advancing high-water; failed
  initialization leaves no partial requested roots; coordinator and remote agent
  start from supported commands/configuration on a deployment that permits
  persistent role processes.
- Public or durable shapes: summary/list/detail/wait request/results and their
  exact order/revision outcomes; sequenced poll request/state/errors; time state/
  recovery request/receipt; protected deployment bundle/config; and CLI commands.
  All prior touched root/protocol identities are hard-rejected.
- Trust and failure boundaries: status is read-only/redacted; cursor and wait
  inputs are bounded; poll replay is principal/session/digest bound; time recovery
  is operator-authorized; staged root publication never overwrites an existing
  target; service config is protected.
- Cross-phase contracts: this phase consumes, and does not redefine, Phase 10
  scheduling/health and Phase 11 profile/provider/environment behavior.
- Reproducibility and compatibility: cursor and sequence ordering are durable;
  maximum forward step is protected configuration; no old status/poll/runtime
  compatibility or root migration.
- Private choices the executor may simplify: opaque cursor encoding (not its
  ordering semantics), internal summary count queries, config serialization
  format using existing Loom conventions, and service-loop helper placement.

## Proportionality

- Existing seam reused: direct/socket application views, SQLite owner state,
  authenticated session operations, existing CLI command group, and supervisor
  service.
- Material additions and current justification: bounded queries, sequenced poll
  state, explicit time state/recovery, staging initialization, and service config/
  commands close demonstrated unbounded storage/read, hidden failure, time, and
  unsupported deployment paths.
- Optional hardening and future capability deferred: UI, general query language,
  remote coordinator HA, packaging/service managers, migrations, and adapting
  the managed ready-stage bootstrap into an intermittent service-less protocol.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Summary/detail/history costs are explicit and bounded | coordinator query store/application | many terminal admissions/controls | scheduler/status outage or oversized response | many-run bounded status and pagination tests |
| Poll replay uses one monotonic state | session store | retries, stale/gapped clients | unbounded rows or non-idempotent delivery | constant-row and sequence transition tests |
| Admission failures clear only by same-admission success | Phase 10 reconciliation-health store | another run completes successfully | hidden degraded run | failure-isolation integration test and read-only Phase 12 aggregation |
| Suspicious time never advances high-water or schedules | accepted-time state owner | regressed/jumped clock | invalid expiry/fallback/new launch | regression, forward jump, and recovery tests |
| Initialization publishes complete roots only | deployment-bundle/agent-root initializer | crash or failure during role/store creation | partial root accepted as production | crash-cut/failure injection before and after each single-directory rename |
| Supported commands construct the sole production composition | CLI/deployment wiring | divergent embedded/remote defaults | behavior differs by launch method | subprocess coordinator/agent smoke and restart tests |

## Implementation Slices

1. Add store-level count, bounded admission list, targeted detail/wait, and
   nonterminal assignment queries; replace status/transport/CLI consumers.
2. Hard-cut poll schemas/protocol to one sequenced replay state and update agent
   client/service behavior.
3. Add read-only per-admission reconciliation-health aggregation and complete
   the fenced accepted-time state/recovery; gate new scheduling on time health
   and the existing shared/per-admission health owners.
4. Implement single-directory staged publication for the local deployment bundle
   and remote agent role root, with crash-cut tests and no overwrite behavior.
5. Add protected deployment config plus coordinator and outbound-agent service
   commands using the same application composition.
6. Update docs/examples, including the persistent-managed versus service-less
   whole-run SLURM deployment matrix, and run the final causal and full
   validation matrices.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | intentional public operational values/imports | cheap typed imports and hard-cut schemas |
| Unit | required | pagination/cursor, poll sequences, time transitions, initialization | bounds, typed failures, no high-water change, no partial roots |
| Contract | required | direct/socket parity and new operation schemas | same authorization/transitions and exact serialization |
| Integration | required | many runs, failure isolation, service commands/restart | bounded reads/storage and real coordinator/agent reconnect |
| E2E / opt-in | required | supported deployment journey | initialize, serve, register, submit, wait/detail/status, restart |

Targeted commands:

    pytest -q tests/unit/loom/queue/test_local_daemon.py tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_service_client.py tests/unit/loom/cli/test_queue.py
    pytest -q tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_cli_operations.py tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: cursor instability, wait lost wakeups, sequence replay delivering
  different work, stale clock recovery, partial bundle publication, or a
  new command composing different defaults from the tested application.
- Review focus: bounded SQL/API shapes, poll state machine crash/replay, schedule
  gate on time/health, staging publication cleanup, and process-level service
  proof.
- Stop if: requirements demand migration/dual read, a supported publication unit
  cannot use one atomic directory rename without overwriting an existing target,
  or deployment requires an
  unapproved network/service dependency.
- Accepted debt and revisit trigger: no hosted dashboard/service manager; add one
  only for a selected deployment consumer.

## Executor Handoff

- Read section range: this complete phase plan, especially Scope through Risks.
- Safe implementation slices: the six numbered slices in order.
- Decisions not to revisit: summary/list/detail/wait split; monotonic one-row poll
  state; explicit time degradation/recovery; staged fresh-only roots; one
  coordinator config/command and one outbound agent command; no compatibility.
  The commands are optional foreground role applications for permitted service
  hosts, not a universal HPC login-node deployment requirement.
- Conditions requiring manager action: a public request/response ambiguity not
  resolved here, inability to prove atomic initialization, or qualified security/
  lifecycle blocker.

## Workflow State

- Manager preparation: complete; manifest status, verified predecessor merge,
  exact `origin/develop` base, dedicated branch/worktree, source seams,
  fast-path decision, validation commands, and the permitted-service-host versus
  service-less whole-run SLURM boundary are current
- Expanded planning: not needed; correction contracts are maintainer-supplied
- Implementation: retained uncommitted bounded summary/admission/list/detail/
  wait and sequenced-poll work is continuing under the resolved consumer
  contract
- Refiner: correction 1/3 owns the bounded Discord consumer adaptation and only
  the minimal targeted-detail support it requires
- Pre-submit gate: pending; incomplete-tree summaries are non-evidence. The
  collection failure causally identifies the Discord reporter fields corrected
  by the bounded consumer adaptation; a fresh stable-tree gate remains required
- Independent review: not needed unless a material residual risk remains
- Blocker corrections: 1/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Uncommitted partial work currently changes `local_daemon.py`, `local_daemon_transport.py`, `agent_sessions.py`, queue public imports, and their focused unit tests for bounded status/admission operations and sequenced poll state. Deployment, time recovery, initialization, commands, integration, docs, and final hard-cut closure remain incomplete. |
| Tests added or updated | Correction 1/3 adds direct/socket targeted-detail coverage and Discord bounded page/detail collection coverage. Focused `test_local_daemon.py` and `test_discord_webhook.py` pass 49 tests; incomplete-tree additions are not yet accepted phase evidence. |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | The partial tree has no reusable final evidence; full gates must run only after the public deployment contract and all six slices are complete. |
| PR, review, and merge | pending |
| Residual risk and cleanup | The public deployment and Discord consumer contracts are resolved. Correction 1/3 preserves exact reporter behavior through bounded pages/details without enlarging the summary or scheduler path; the dedicated worktree and branch retain the remaining implementation. |
