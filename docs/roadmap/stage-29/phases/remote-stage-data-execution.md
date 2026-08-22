# Phase 5 Execution Plan: Remote Stage Data And Execution

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 5
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p5-remote-stage-data-execution`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 4 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): execute stages on remote agents`
- Dependencies: Phase 4 merged with authenticated role views, agent sessions,
  safe CPU/memory offers, long-poll ownership, and a passing no-launch transport
  gate; Phase 2 provides the assignment/grant/launch saga
- Workflow path: expanded because authenticated control, artifact bytes,
  cross-host process launch, coordinator outage, and replay interact causally
- Blockers: Phase 4 remote merge; remote launch must remain disabled until the
  Phase 4 security/connectivity receipt is verified on the implementation tree

## Objective And Context

- Vertical outcome: a client submits runs to the coordinator and ready CPU/
  memory stages execute on an authorized agent on `machine-A` or `machine-B`.
  The coordinator selects the target JIT from global fresh capacity; the agent
  durably receives the request and inputs, physically admits resources, receives
  a grant, launches once, retains outputs, and reports/finalizes them. A granted
  stage continues while the coordinator or lifecycle authority is unavailable
  and reconciles after both required owners return.
- Earlier dependency: Phase 4 proves who is talking and what operations they may
  request. It deliberately cannot deliver an assignment. Phase 5 enables remote
  side effects by reusing the Phase 2 saga over that authenticated boundary.
- Later work explicitly out of scope: Phase 6 adds GPU/VRAM inventory, device
  binding, and advanced placement preferences. Phase 7 adds drain/reload and
  complete cancellation. Phase 8 adds same-session process recovery and
  containment-gated takeover.

## Current Source And Harness

- Reuse Phase 1 kernel/CPU-memory planners, Phase 2 coordinator/authority/agent
  saga and artifact port, Phase 3 status/facades, and Phase 4 HTTP/session/offer/
  long-poll/idempotency boundary.
- Rediscover existing artifact backend capabilities, payload-operation codecs,
  local materialization safety, digest helpers, atomic write utilities, stage
  worker request reconstruction, and process-containment fixtures.
- Current local artifact handling supports both files and directories, while its
  materialization path is local-path based. The initial remote relay deliberately
  supports immutable regular-file payloads only; it must advertise and enforce
  that capability rather than treating a directory as a file or inventing an
  archive format implicitly.
- Reuse fake transports/clocks, loopback TLS, process barriers, temporary stores,
  fault-injected artifact backends, and multi-run scheduler tests.
- Default CI uses two logical agents over loopback. Real two-machine execution is
  opt-in and must not be required for the implementation gate.

## Scope

In scope:

- Build immutable global scheduling snapshots from admitted runs' ready stage
  work and every fresh authorized CPU/memory offer. Preserve deterministic work
  order, per-run concurrency, hard-before-soft evaluation, and stable candidate
  IDs from Phase 1.
- Add built-in hard feasibility for authorized pool, exact/hard agent target,
  session/offer freshness, CPU count, memory bytes, project/environment/executor
  compatibility, resource claim contract, and artifact-transfer capability.
  An unsupported resource remains pending with a bounded reason; it is not sent
  speculatively.
- Include payload form in artifact-transfer capability matching. A remote
  candidate is feasible only when every bound input and declared output can be
  proven compatible with the initial immutable regular-file relay. Directory,
  tree, special-file, or ambiguous payload forms make that remote candidate
  ineligible with a safe diagnostic; an eligible local candidate may still run
  the stage normally.
- Implement one agent-wide inventory/availability domain projected into every
  authorized pool. Capacity identities are shared across views. Coordinator
  policy intersects pool membership; one offer cannot multiply capacity.
- Treat agent availability as net remaining atoms naming the live claims already
  reflected. Subtract only newer unreflected coordinator reservations. Permit
  one unresolved remote admission from an availability revision and require a
  reconcile/fresh revision after accept or decline.
- Treat that rule as serialization of admission decisions, not serialization of
  execution. Once an accepted claim is journaled and reflected in a fresh net-
  availability revision, the agent may issue the next work request and accept a
  disjoint assignment against remaining atoms while earlier processes continue.
  Agent/process concurrency limits and transfer quotas remain hard bounds.
- Keep scheduling decision and mutation separate. The coordinator selects one
  validated candidate outside its transaction, then atomically revalidates and
  persists assignment/reservation against exact work, authority, coordinator
  generation, agent/session/config/inventory/availability/work-request, pool,
  claim-contract, and capacity revisions.
- Use outbound revision-bound long polling as delivery transport. The
  coordinator owns the queue and scheduling choice, persists the targeted
  assignment first, then wakes the exact agent request. Agents keep no
  coordinator-created backlog. If work arrives after local drift, final
  admission may definitively decline before grant.
- Add resident-project capability matching. Remote work is a prepared stage
  identity and immutable versioned request, not shell text or a code bundle.
  Agent config advertises safe project/environment/executor fingerprints; the
  worker reconstructs only an explicitly configured resident project.
- Implement one bounded coordinator-mediated artifact relay over the existing
  assignment-scoped artifact port:
  - coordinator issues opaque transfer IDs bound to assignment, fence,
    direction, logical artifact names, digests, sizes, principal, and expiry;
  - staging locations are derived under role-owned roots, never supplied by a
    request;
  - no operation accepts an arbitrary fetch URL or host path;
  - transfers enforce per-object, assignment, principal, agent, and retained-
    byte quotas plus concurrency/high-water limits;
  - writes reject traversal, absolute paths, symlinks/hard-link surprises,
    unexpected file types, duplicate logical names, size/digest mismatch, and
    unsupported versions;
  - data is written no-follow to a temporary file, flushed, verified, safely
    permissioned, atomically renamed, and reconciled with the journal before it
    is considered durable.
- The Phase 5 relay transfers regular files only. A future directory/tree
  contract requires an explicit bounded manifest/archive format, path and link
  rules, quotas, digest semantics, and a real consumer; it is not inferred from
  the existing local directory artifact behavior.
- Stage the immutable work request and all required input payloads on the agent
  before it may acknowledge physical acceptance and before the coordinator may
  promote a grant. An interrupted input transfer resumes or restarts the same
  transfer identity and cannot expose partial content to the worker.
- Implement the remote daemon as one session control loop supervising bounded
  per-assignment flows. It reconciles/outbox-replays and publishes fresh
  capacity; each flow receives an exact assignment, stages inputs, prepares,
  accepts/declines, receives grant, activates, journals start, launches once,
  retains/reports output, and releases. After definitive accept or decline it
  publishes a fresh net-availability revision and may request another disjoint
  assignment immediately; it does not wait for an accepted process to finish
  before using remaining capacity.
- Do not pre-issue output upload capabilities. After containment/execution the
  agent durably records a manifest of expected logical names, digests, and
  sizes, then requests idempotent short-lived grants bound to that manifest and
  current assignment fence.
- Publish output through coordinator-owned durable staging/backend operations.
  Finalize individual content first and publish the complete manifest last.
  Authority terminal commit receives only coordinator/backend-accessible final
  `ArtifactRef` values; agent-local refs and partial uploads cannot unlock a
  descendant.
- Allow granted work to continue during coordinator/network interruption because
  request/inputs, physical claim, grant/start fence, and process ownership are
  already durable locally. Buffer critical events, result, manifest, output,
  cleanup status, and outbox until the coordinator returns.
- Treat lifecycle-authority interruption similarly for already-granted work but
  more strictly for new work: the coordinator pauses preparation, assignment
  binding, grant/delivery, and terminal commit. Agents continue only grants they
  already hold and retain events/output; they never reconnect to authority
  directly. After authority restart, Phase 3's authenticated generation-
  continuity reconciliation must complete before the coordinator resumes any
  lifecycle operation or acknowledges terminal output.
- On coordinator restart, authenticate the new generation, reconcile exact
  durable session/assignment/fence/event facts, finish output publication, and
  only then advertise fresh capacity. A valid authority execution fence remains
  usable across coordinator liveness/generation change.
- On authority restart, authenticate its service principal, verify configured
  workspace/schema/capabilities, and compare the complete retained-run
  continuity set. Every coordinator-retained admitted run must reproduce its
  last-acknowledged authority revision and canonical full-snapshot fingerprint;
  each nonterminal attempt and execution fence must match exactly. Atomically
  record the rotated authority generation only when all facts agree. A pristine
  empty authority is valid only when the coordinator has no retained admitted
  run. Old-generation calls, missing expected truth, a replacement service,
  partial reads, and divergent snapshots fail closed while retained agent
  results remain unacknowledged.
- On agent disconnection, expire future capacity but retain accepted assignments
  and reservations as unknown. Never automatically allocate that stage elsewhere
  or consume retry budget. Other independent work may run on other agents.
- If the agent process restarts in this phase, it starts at zero availability,
  replays known terminal/outbox facts, and refuses to repeat an uncertain start.
  Phase 8 owns full process recovery/adoption and privileged closure; uncertainty
  remains visible until then.
- Add joined status/diagnostics for target offline, no compatible project,
  unsupported resource, stale offer, transfer pending/failure/quota, active
  remote assignment, coordinator disconnected, retained output, and unknown
  execution. Keep codes bounded and redacted.
- Add client/agent HTTP operations for assignment delivery, accept/decline,
  grant, transfer authorization/chunks/finalization, event/result/output report,
  acknowledgements, and reconciliation. Reuse Phase 4 authentication,
  authorization, versions, limits, and idempotency for every operation.

Out of scope:

- GPU inventory/claims, model/VRAM preferences, sharing/fractional modes, general
  topology, or solver behavior.
- Peer-to-peer transfer, arbitrary URL fetch, shared-filesystem signalling,
  direct selected object-store SDK, arbitrary code/config shipment, or hostile
  content safety claims. Digest/type checks prove integrity, not benign content.
- Directory/tree/special-file remote payload transfer or an implicit archive
  format. These payloads remain supported by eligible local execution and are
  reported as unsupported for the initial remote relay.
- Automatic retry/reassignment of unknown accepted work, remote drain/reload,
  complete disconnected cancellation, session takeover, coordinator HA, or
  exactly-once authored effects.

Assumptions:

- The same trusted project/environment can be provisioned independently on each
  eligible agent and identified by configured fingerprints.
- The initial relay throughput is adequate for accepted workloads. Its narrow
  assignment-scoped port permits a future selected backend without changing
  authority output semantics.
- Agent-local storage can retain request/input/result/output through an ordinary
  coordinator outage within configured quotas.

## Fixed Contracts And Private Discretion

### JIT assignment topology

Polling is transport, not the scheduling decision:

```text
agent publishes fresh availability and waits
coordinator sees ready work and all fresh offers
coordinator kernel chooses one validated candidate
coordinator transaction persists targeted assignment/reservation
coordinator wakes that exact agent request
agent performs final physical/data admission
```

A newly submitted high-priority run can wake an already waiting agent as soon as
the coordinator commits an assignment. There is no need to preload daemon
queues, and an agent cannot choose arbitrary work from the global queue.

### Transfer capability

Conceptually:

```python
@dataclass(frozen=True)
class TransferGrant:
    transfer_id: str
    assignment_id: str
    execution_fence: str
    direction: Literal["input", "output"]
    logical_name: str
    expected_digest: str
    expected_size: int
    expires_at: Timestamp
```

The grant contains no filesystem location or arbitrary URL. The authenticated
adapter verifies principal/session and the application revalidates assignment,
fence, manifest, quota, and expiry on every mutating operation.

### Output sequencing

```text
process contained/finished
  -> output manifest durable on agent
  -> request manifest-bound upload grants
  -> content streamed and verified into coordinator staging
  -> backend/final refs durable
  -> complete output manifest published
  -> authority terminal/output commit
  -> coordinator ack
  -> agent may clean output and release
```

No preissued broad upload token survives to accept unexpected files. A transfer
retry with the same digest/size is idempotent; changed content conflicts.

### Outage truth

Connection, coordinator generation, and authority service-generation facts
govern communication/current mutations only. They do not by themselves revoke
an accepted assignment, execution fence, physical claim, or result:

```python
if offer.expired:
    remove_future_capacity(agent)

if assignment.accepted and not reconciled:
    keep_reserved_unknown(assignment)
```

Only authoritative terminal truth or the Phase 8 guarded containment flow can
fence and optionally replace unknown accepted work.

### Private discretion

Chunk size, HTTP streaming implementation, scheduling-loop batching, relay
worker count, private workspace layout, and retry backoff are implementation
choices within configured bounds. The executor may not accept caller paths/
URLs, grant before inputs, publish partial outputs, or infer failure from loss.

## Proportionality

- Reuses every semantic side of the Phase 2 saga and every trust/session side of
  Phase 4. Adds only the real remote data and process adapters required by the
  accepted two-machine CPU/memory consumer.
- Artifact relay stays with its first execution consumer so its capability and
  durability contract are validated by a real end-to-end trace rather than an
  unused speculative API.
- GPU and operational recovery remain later, keeping this phase focused on one
  remote execution mode and its causal transfer/outage boundaries.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Capacity is not duplicated across pools | Registration policy + availability domain | Same offer projected to several pools | Oversubscription | Cross-pool concurrent assignment tests |
| Admission serialization does not serialize disjoint execution | Agent control loop + availability revisions | Single blocking work loop | Idle CPUs/GPUs and misleading pool behavior | Two same-agent disjoint assignments overlap; same-atom requests cannot |
| Assignment targets exact current work/request/revisions | Coordinator transaction | Stale kernel result/poll | Wrong/duplicate delivery | Version/CAS barrier matrix |
| Inputs and request are durable before grant | Agent journal + transfer adapter | Interrupted/partial transfer | Worker sees incomplete data | Crash/chunk/digest tests |
| Transfer cannot select storage/network target | Capability and derived staging owner | Crafted path/URL/name | Traversal/SSRF/data overwrite | Negative path, URL, symlink, type tests |
| Unsupported payload forms never enter the relay | Transfer capability matcher | Directory/ambiguous input or output | Truncation, traversal, or false artifact publication | Local-fallback/pending diagnostics and no-transfer sentinel tests |
| One remote root launch | Agent grant/start fence | Redelivery/reconnect/crash | Duplicate work | Real process barrier tests |
| Only complete accessible refs commit | Relay/backend + authority transaction | Partial/local output | Broken lineage/downstream failure | Manifest-last and ref-access tests |
| Coordinator loss does not cancel granted work | Authority fence + agent journal | TTL/generation/connection loss | Lost valid result | Disconnect/restart replay E2E |
| Authority loss pauses mutation but not a grant | Authority adapter/generation reconciler + agent journal | Service outage or rotated generation | Duplicate launch, lost terminal history/result, or attachment to false truth | Same-repository restart plus pristine-bootstrap and missing/divergent retained-run E2E |
| Agent loss does not duplicate unknown work | Coordinator recovery policy | Offer expiry/timeout | Duplicate authored effects | Multi-agent outage tests |
| Secrets/errors stay bounded | Adapter/status/audit | Worker/provider/network exception | Credential/path disclosure | Worker-env and redaction tests |

## Implementation Slices

1. Add cross-agent CPU/memory snapshots, one cross-pool availability/reservation
   domain, JIT targeted assignment delivery, exact revision revalidation,
   fresh-revision concurrency for disjoint claims, and remote definitive
   decline/accept conformance without enabling launch.
2. Implement regular-file transfer capability matching, assignment-scoped input
   relay, derived safe staging, quotas, temporary-first/digest verification,
   resident-project capability matching, and request/input-before-grant fault
   tests.
3. Implement remote grant/start/worker loop, result/outbox persistence, post-run
   output manifest/grants, manifest-last finalization, authority commit, release,
   and one-launch/process barriers.
4. Implement coordinator-disconnect/generation reconciliation, authority-outage
   and rotated-generation continuity barriers, agent zero-availability fail-
   closed restart, unknown-work retention, joined status, Python/CLI operations,
   abstract deployment docs, and multi-run/two-agent E2E.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | No artifact/network dependency enters scheduling core | Import direction and optional transport composition |
| Unit | Required | Capacity merge, transfer grants/limits, staging, output manifests | Exact revisions/atoms, regular-file capability, directory/ambiguous rejection, path/type/digest/size/quota boundaries |
| Contract | Required | Direct/HTTP agent and artifact operations | Same authz/idempotency/state/errors; invalid fence/session/version no mutation |
| Integration | Required | Remote saga, real process, transfer and outage crash points | Barrier before/after input, accept, fresh availability, grant, start, result, upload, commit, ack; coordinator/authority outage; rotated authority retained-run continuity, pristine-bootstrap, and missing/divergent negatives; disjoint same-agent overlap and same-atom exclusion |
| E2E / opt-in | Required loopback; optional two-machine | CPU/memory multi-agent execution | Two runs on logical agents, including concurrent use of remaining capacity; coordinator and authority outage/replay; agent loss no reassign; optional abstract network receipt |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: double-counted pool capacity; grant before durable inputs;
  traversal/SSRF or quota bypass; partial output commit; stale delivery; treating
  a directory as a regular file; disconnect as failure; or leaking daemon
  credentials to worker; or accepting a rotated authority without complete
  retained-run continuity.
- Review focus: full remote trace, transfer capability scope, filesystem safety,
  output ordering, revision/idempotency checks, coordinator/authority outage and
  generation barriers, and status redaction.
- Stop if: the existing artifact abstraction cannot return accessible refs;
  HTTP streaming cannot enforce bounded temporary-first writes; resident-project
  identity is not reconstructable; coordinator or correctly reconciled authority
  restart invalidates execution fences; rotated authority continuity cannot be
  proven; or an accepted assignment would need automatic timeout release.
- Accepted debt: coordinator relay throughput and retained agent output are
  bounded operational costs. Revisit with measurements or a selected direct
  backend.

## Executor Handoff

- Read this file, Phase 4 completion record, manifest trace/security constraints,
  and planning FR-1, FR-8–FR-13, FR-15–FR-17, FR-19, FR-20, FR-25, FR-26, and
  DQ-14.
- Keep remote launch disabled until slices 1–2 and the Phase 4 gate pass. Use
  real process barriers for grant/start/outage rather than mocks alone.
- Decisions not to revisit: coordinator chooses JIT, outbound polling, inputs
  before grant, output grants after manifest, accessible refs before commit, and
  no automatic unknown-work reassign.
- Escalate any need for arbitrary URLs/paths, code shipment, new heavyweight
  dependency, weakened quota, or changed authority ownership.

## Workflow State

- Manager preparation: pending Phase 4 merge, worktree/base recording, and
  exact artifact/process/transport rediscovery
- Expanded planning: required by remote code/data/outage interaction; phase plan
  finalized
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: expected because this is the first remote code and data
  execution phase; confirm during preparation
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
