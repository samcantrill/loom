# Phase 5 Execution Plan: Remote Stage Data And Execution

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 5
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p5-remote-stage-data-execution`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p5-remote-stage-data-execution`
- Base revision: clean `origin/develop`
  `4d0a9bb6708752d711701885a793dd28b915571d`
- PR target: `develop`
- PR title: `feat(scheduling): execute stages on remote agents`
- Dependencies: Phase 4A [PR #239](https://github.com/samcantrill/loom/pull/239)
  squash-merged as `2d273b8` with authenticated role views, agent sessions,
  safe CPU/memory offers, long-poll ownership, and a passing no-launch transport
  gate; Phase 2 provides the assignment/grant/launch saga
- Workflow path: expanded because authenticated control, artifact bytes,
  cross-host process launch, coordinator outage, and replay interact causally
- Blockers: the required independent review found a publish-before-SQLite-commit
  crash window in both input and output transfer finalization. After the rename
  publishes verified bytes and removes the staging file, a crash can leave the
  durable transfer row unfinished; exact replay then rejects the missing/short
  staging file and strands the assignment. Correction 3/3 is exhausted, so this
  phase stops without a PR. The maintainer-approved hard cut-over remains:
  protected resident profiles and paths stay agent-local, wire requests are
  path-free, and old protocol/root/request schemas receive no compatibility or
  migration support.

## Objective And Context

- Vertical outcome: a client submits runs to the coordinator and ready CPU/
  memory stages execute on an authorized agent on `machine-A` or `machine-B`.
  The coordinator selects the target JIT from global fresh capacity; the agent
  durably receives the request and inputs, physically admits resources, receives
  a grant, launches once, retains outputs, and reports/finalizes them. A granted
  stage continues while the coordinator or lifecycle authority is unavailable
  and reconciles after both required owners return.
- Earlier dependency: Phase 4A proves who is talking and what operations they may
  request. It deliberately cannot deliver an assignment. Phase 5 enables remote
  side effects by reusing the Phase 2 saga over that authenticated boundary.
- Later work explicitly out of scope: Phase 6 adds GPU/VRAM inventory, device
  binding, and advanced placement preferences. Phase 7 reuses the execution-
  only worker and relay for an assignment-scoped SLURM bootstrap. Phase 8 adds
  drain/reload and complete cancellation. Phase 9 adds same-session process
  recovery and containment-gated takeover.

## Current Source And Harness

- Reuse Phase 1 kernel/CPU-memory planners, Phase 2 coordinator/authority/agent
  saga and artifact port, Phase 3 status/facades, and Phase 4A HTTP/session/offer/
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
  work and every fresh authorized CPU/memory offer. Validate/canonicalize each
  resource opportunity once through its planner, require complete per-resource
  and composite search, and preserve deterministic grouped work order,
  hard-before-soft evaluation, and stable candidate IDs from Phase 1. Semantic
  ready-work projection remains independent of per-run concurrency; the
  assignment transaction owns the limit.
- CPU count and memory bytes are intrinsic planner-owned feasibility. Add
  built-in complete-placement hard feasibility for authorized pool, exact/hard
  agent target, session/offer freshness, project/environment/executor
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
  validated work/candidate pair outside its transaction, then atomically revalidates and
  persists assignment/reservation against exact work, authority, coordinator
  stable ID/current process epoch, agent/session/config/inventory/availability/work-request, pool,
  claim-contract, and capacity revisions. The same CAS rechecks
  `max_parallel_stages` against all active assignment states and records the
  bounded policy-epoch decision receipt established in Phase 2.
- Persist the stable coordinator ID, current process epoch, and immutable
  assignment issuer epoch separately. Current epoch is required for new
  delivery, grant, control, and transfer authorization. A later coordinator
  epoch may accept old-issuer facts only inside explicit reconciliation for the
  exact retained assignment/session/fence; it cannot manufacture a new mutation
  under the old epoch.
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
  - coordinator issues an opaque stable transfer ID bound to assignment, fence,
    direction, immutable logical artifact names/digests/sizes, and separately
    issues renewable short-lived authorization IDs/revisions bound to principal,
    current coordinator epoch, and expiry;
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
  - authorization expiry rejects later chunks under that authorization but does
    not delete durable progress, change transfer/assignment state, or permit
    cleanup. Reauthorization resumes the same transfer; exact offset/content and
    finalize replay is idempotent, while conflicting overlap/content fails.
  Relay authorization is based on a narrow authenticated assignment principal,
  not on agent offers or pool identity internally. This phase composes the agent
  principal. Phase 7 may compose its separate restricted SLURM-bootstrap
  principal for the same exact assignment/fence/manifest operations, without
  gaining an arbitrary path/URL, agent session, or broader service authority.
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
- Journal every critical assignment event before send with its stable event ID
  and monotonic assignment sequence. Replay sends from the first unacknowledged
  sequence. Coordinator accepts next-or-exact-replay, returns typed gaps, and
  acknowledges only durably persisted contiguous evidence. Timeout, disconnect,
  cancelled poll, or 5xx after send is indeterminate and retries the same
  operation identity/digest; transport completion is never a lifecycle fact.
- Do not pre-issue output upload capabilities. After containment/execution the
  agent durably records a manifest of expected logical names, digests, and
  sizes, then creates/reuses the immutable transfer and requests idempotent
  short-lived authorization revisions bound to that manifest and current
  assignment fence.
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
- On coordinator restart, authenticate the same stable coordinator ID and new
  process epoch, reconcile exact
  durable stable coordinator identity, new process epoch, and old-issuer
  session/assignment/fence/ordered-event facts, finish output publication, and
  only then advertise fresh capacity. A valid authority execution fence remains
  usable across coordinator liveness/generation change.
- On authority restart, authenticate its service principal, verify configured
  workspace/schema/capabilities, and compare one authority-owned consistent cut
  of the complete authority-relevant continuity set. Every retained admission or
  tombstone must reproduce its
  last-acknowledged authority revision and canonical full-snapshot fingerprint;
  or its ordered forward changes must be explained by authority receipts for
  coordinator-durable operation IDs/digests/principals/expected states. Each
  resulting nonterminal attempt and execution fence must match exactly.
  Atomically record the verified receipt chain and rotated authority generation
  only when all facts agree; actionable receipts remain retained under their
  safety policy. A pristine empty authority is valid only when the
  coordinator has no authority-relevant retained admission/tombstone. The
  authority holds a mutation barrier for the cut or returns an equivalent
  atomically changing token. Old-generation calls, missing receipts/truth, a
  replacement service, regression/unexplained change, torn/partial reads, and
  divergent snapshots fail closed while retained agent results remain
  unacknowledged.
- On agent disconnection, expire future capacity but retain accepted assignments
  and reservations as unknown. Never automatically allocate that stage elsewhere
  or consume retry budget. Other independent work may run on other agents.
- If the agent process restarts in this phase, it starts at zero availability,
  replays known terminal/outbox facts, and refuses to repeat an uncertain start.
  Phase 9 owns full process recovery/adoption and privileged closure; uncertainty
  remains visible until then.
- Add owner-labelled joined status/diagnostics for target offline, no compatible project,
  unsupported resource, stale offer, transfer pending/failure/quota, active
  remote assignment, coordinator disconnected, retained output, and unknown
  execution. Preserve admission/control, authority lifecycle/cancellation,
  scheduling/placement, assignment/execution, transfer, and service-health axes
  with owner revisions, coordinator-accepted receipt times, freshness, and a join
  `as_of`. The read is not globally atomic and remote wall clocks establish no
  order/freshness. Keep codes bounded and redacted; stale operational facts
  cannot overwrite authority terminal truth.
- Add client/agent HTTP operations for assignment delivery, accept/decline,
  grant, transfer authorization/chunks/finalization, event/result/output report,
  acknowledgements, and reconciliation. Reuse Phase 4A authentication,
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

The versioned application exchange is conceptually:

```text
agent -> coordinator: Offer(session, config/inventory/availability revisions)
agent -> coordinator: RequestWork(work_request_id, availability_revision)
coordinator -> agent: Wait | Assignment(issuer epoch, stage work, claim, inputs)
agent -> coordinator: DefinitiveDecline | Prepared(composite claim receipt)
coordinator -> agent: Grant(execution fence, process_execution_id)
agent -> coordinator: Event(event_id, assignment sequence, fenced fact)
coordinator -> agent: Ack(highest durably contiguous sequence)
```

The agent initiates each exchange over its authenticated session; remote agents
need no inbound port. A control or new assignment may complete the current
outstanding request, after which the agent renews the revision-bound poll. Every
mutation verifies current principal policy, coordinator/process/session/fence
identity, expected revisions, and canonical request digest. Timeout or 5xx after
send leaves the result unknown and retries the same operation identity; an HTTP
response class alone never authorizes bind, grant, relaunch, cleanup, or retry.

After one prepared/accepted claim is reflected in a new net availability
revision, the agent may publish remaining disjoint capacity and hold another
work request while the first process continues. Before that refresh, at most one
admission may remain unresolved against the old revision, preventing two
assignments from consuming the same stale atoms.

### Transfer capability

Conceptually:

```python
@dataclass(frozen=True)
class TransferGrant:
    transfer_id: str
    authorization_id: str
    authorization_revision: int
    assignment_id: str
    execution_fence: str
    direction: Literal["input", "output"]
    logical_name: str
    expected_digest: str
    expected_size: int
    expires_at: Timestamp
```

`transfer_id` is the durable content/progress identity; authorization ID,
revision, and expiry are temporary permission to mutate it. The grant contains
no filesystem location or arbitrary URL. The authenticated adapter verifies
principal/session/current coordinator epoch and the application revalidates
assignment, fence, immutable manifest, quota, and authorization expiry on every
mutating operation. Expiry requires a new authorization revision for the same
transfer and never disposes its journal/staged bytes.

### Output sequencing

```text
process contained/finished
  -> output manifest durable on agent
  -> create/reconcile stable transfer + request short-lived authorization
  -> content streamed and verified into coordinator staging
  -> backend/final refs durable
  -> complete output manifest published
  -> authority terminal/output commit
  -> coordinator durably persists/acks the contiguous assignment event
  -> coordinator releases logical reservation
  -> agent releases exact provider claim and publishes fresh availability
  -> agent may clean retained output after its acknowledgement contract
```

No preissued broad upload token survives to accept unexpected files. Exact
offset/content/finalize replay for the immutable transfer is idempotent;
changed or overlapping conflicting content fails. Authorization expiry, a lost
response, or coordinator restart retains progress and output until renewed,
finalized, authority-committed, and durably acknowledged.

### Outage truth

Connection, coordinator process epoch, and authority service-generation facts
govern communication/current mutations only. They do not by themselves revoke
an accepted assignment, execution fence, physical claim, or result:

```python
if offer.expired:
    remove_future_capacity(agent)

if assignment.accepted and not reconciled:
    keep_reserved_unknown(assignment)
```

Only authoritative terminal truth or the Phase 9 guarded containment flow can
fence and optionally replace unknown accepted work.

An assignment retains its issuer epoch. After coordinator restart, the new
epoch may reconcile exact sequenced facts for that assignment, but an old
connection cannot request new work, grant, control, or transfer capability.

### Private discretion

Chunk size, HTTP streaming implementation, scheduling-loop batching, relay
worker count, private workspace layout, and retry backoff are implementation
choices within configured bounds. The executor may not accept caller paths/
URLs, grant before inputs, publish partial outputs, or infer failure from loss.

## Proportionality

- Reuses every semantic side of the Phase 2 saga and every trust/session side of
  Phase 4A. Adds only the real remote data and process adapters required by the
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
| Remote opportunity is canonical and complete before selection | Resource planner + scheduling kernel | Malformed authenticated offer or exhausted search | Repeated failure, wrong quantity, or unproven winner | Opportunity-invalid, complete/exhausted, no-mutation, and later-work bypass tests |
| Admission serialization does not serialize disjoint execution | Agent control loop + availability revisions | Single blocking work loop | Idle CPUs/GPUs and misleading pool behavior | Two same-agent disjoint assignments overlap; same-atom requests cannot |
| Assignment targets exact current work/request/revisions and run slot | Coordinator transaction | Stale kernel result/poll or concurrent cycle | Wrong/duplicate delivery or concurrency overflow | Version/final-slot CAS barrier matrix plus decision-receipt round trip |
| Inputs and request are durable before grant | Agent journal + transfer adapter | Interrupted/partial transfer | Worker sees incomplete data | Crash/chunk/digest tests |
| Transfer cannot select storage/network target | Capability and derived staging owner | Crafted path/URL/name | Traversal/SSRF/data overwrite | Negative path, URL, symlink, type tests |
| Transfer progress outlives temporary authorization safely | Transfer journal + authorizer | Expiry, response loss, or coordinator epoch change mid-stream | Lost/duplicated bytes, stale capability use, or orphan staging | Exact chunk/finalize replay, conflicting overlap, expiry rejection, renewed authorization, and restart tests |
| Unsupported payload forms never enter the relay | Transfer capability matcher | Directory/ambiguous input or output | Truncation, traversal, or false artifact publication | Local-fallback/pending diagnostics and no-transfer sentinel tests |
| One remote root launch | Agent grant/start fence | Redelivery/reconnect/crash | Duplicate work | Real process barrier tests |
| Event/result replay is ordered and survives coordinator epoch change | Agent journal/outbox + coordinator event transaction | Gap, duplicate, timeout-after-commit, or old issuer | Lost terminal fact, duplicate mutation, or stale new operation | Sequence/gap/contiguous-ack and old-issuer-reconcile/current-operation tests |
| Only complete accessible refs commit | Relay/backend + authority transaction | Partial/local output | Broken lineage/downstream failure | Manifest-last and ref-access tests |
| Coordinator loss does not cancel granted work | Authority fence + agent journal | TTL/generation/connection loss | Lost valid result | Disconnect/restart replay E2E |
| Authority loss pauses mutation but not a grant | Authority adapter/durable operation intents/receipt-aware consistent-cut reconciler + agent journal | Commit-before-response plus dual restart, rotated generation, or torn continuity read | Permanent false degradation, duplicate launch, lost terminal history/result, or attachment to false truth | Exact and receipt-explained same-repository restart plus mutation-barrier, pristine-bootstrap, and regressed/missing/unexplained negatives |
| Status keeps owner facts and freshness without trusting remote clocks | Joined status projector | Partial outage, interleaved read, stale event, or clock skew | False terminal/healthy/released view | Owner revision/coordinator-accepted receipt-time/`as_of`, precedence, and stale/degraded tests |
| Agent loss does not duplicate unknown work | Coordinator recovery policy | Offer expiry/timeout | Duplicate authored effects | Multi-agent outage tests |
| Secrets/errors stay bounded | Adapter/status/audit | Worker/provider/network exception | Credential/path disclosure | Worker-env and redaction tests |

## Implementation Slices

1. Add cross-agent CPU/memory snapshots with opportunity validation and
   complete search, one cross-pool availability/reservation domain, JIT targeted
   assignment delivery, exact revision/run-slot revalidation and decision receipt,
   fresh-revision concurrency for disjoint claims, and remote definitive
   decline/accept conformance without enabling launch.
2. Implement regular-file transfer capability matching, stable transfer identity
   plus renewable authorization, assignment-scoped input relay, derived safe
   staging, quotas, temporary-first/digest verification,
   resident-project capability matching, and request/input-before-grant fault
   tests.
3. Implement remote grant/start/worker loop, monotonic event/result/outbox
   persistence and contiguous acknowledgement, post-run
   output manifest/transfer authorization, manifest-last finalization, authority commit, release,
   and one-launch/process barriers.
4. Implement same-coordinator/new-epoch reconnect with exact old-issuer replay,
   authority-outage and receipt-aware rotated-generation consistent-cut barriers, agent zero-
   availability fail-closed restart, unknown-work retention, owner-labelled
   joined status, Python/CLI operations, abstract deployment docs, and multi-run/
   two-agent E2E.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | No artifact/network dependency enters scheduling core | Import direction and optional transport composition |
| Unit | Required | Opportunity validation/search, capacity merge, stable transfer/authorization/limits, staging, output manifests | Malformed offers, complete/exhausted outcomes, exact revisions/atoms, regular-file capability, directory/ambiguous rejection, path/type/digest/size/quota boundaries, authorization expiry/renewal, exact/conflicting chunk replay |
| Contract | Required | Direct/HTTP agent and artifact operations | Same authz/idempotency/definite-versus-indeterminate/state/errors; invalid fence/session/epoch/version no mutation; ordered gap response |
| Integration | Required | Remote saga, assignment concurrency, ordered replay, real process, transfer and outage crash points | Final run-slot race and decision receipt; barrier before/after input, accept, fresh availability, grant, start, result, authorization expiry/renewal, upload, commit, ack; duplicate/gap and timeout-after-commit; same coordinator/new epoch accepts exact old-issuer facts but rejects old new-work operations; coordinator/authority outage; exact or receipt-explained rotated authority cut including commit-then-timeout dual restart, pristine-bootstrap, torn/missing/regressed/unexplained negatives; disjoint same-agent overlap and same-atom exclusion |
| E2E / opt-in | Required loopback; optional two-machine | CPU/memory multi-agent execution | Two runs on logical agents, including concurrent use of remaining capacity; coordinator and authority outage/replay; agent loss no reassign; optional abstract network receipt |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: double-counted pool capacity; grant before durable inputs;
  traversal/SSRF or quota bypass; partial output commit; stale delivery; treating
  a directory as a regular file; disconnect as failure; event-gap acceptance;
  rejecting valid old-issuer facts or accepting stale new operations; leaking
  daemon credentials to worker; conflating transfer authorization expiry with
  content disposal; or accepting a rotated authority from a torn, unexplained,
  or incomplete authority-relevant cut.
- Review focus: full remote trace, transfer capability scope, filesystem safety,
  output ordering, revision/idempotency checks, coordinator/authority outage and
  stable-ID/process-epoch boundaries, event sequencing/ack durability,
  consistent-cut generation barriers, and owner-labelled status/redaction.
- Stop if: the existing artifact abstraction cannot return accessible refs;
  HTTP streaming cannot enforce bounded temporary-first writes; resident-project
  identity is not reconstructable; coordinator or correctly reconciled authority
  restart invalidates execution fences; rotated authority continuity cannot be
  proven; or an accepted assignment would need automatic timeout release.
- Accepted debt: coordinator relay throughput and retained agent output are
  bounded operational costs. Revisit with measurements or a selected direct
  backend.

## Executor Handoff

- Read this file, Phase 4A completion record, manifest trace/security constraints,
  and planning FR-1, FR-8–FR-13, FR-15–FR-17, FR-19, FR-20, FR-25, FR-26, and
  DQ-14, DQ-20, DQ-23, and DQ-24.
- Keep remote launch disabled until slices 1–2 and the Phase 4A gate pass. Use
  real process barriers for grant/start/outage rather than mocks alone.
- Decisions not to revisit: coordinator chooses JIT, outbound polling, inputs
  before grant, output grants after manifest, accessible refs before commit, and
  monotonic durable event replay, current-epoch new operations with exact old-
  issuer reconciliation, consistent authority continuity cuts, owner-labelled
  status, and no automatic unknown-work reassign.
- Escalate any need for arbitrary URLs/paths, code shipment, new heavyweight
  dependency, weakened quota, or changed authority ownership.

## Workflow State

- Manager preparation and expanded planning: complete; the final hard-cutover
  resident-profile/assignment-workspace boundary was maintainer-approved
- Implementation: complete at source/test candidate `d536a1e`; global CPU/memory
  placement, path-free delivery, bounded relay, durable grant/start/result,
  contained resident process, authority commit, replay, and release are wired
  through production direct and HTTP paths
- Pre-submit gate: complete. `make validate-pr` passed 2,435 default and 141
  configuration-extra tests with 3 expected skips plus lint, zero-error pyright,
  and builds; fresh `make test-summary` recorded 2,576 categorized passes
- Independent review: complete; one product blocker found. Input and output
  publication precede matching SQLite finalization, so exact post-publication
  crash replay must verify and adopt an already-published target. No other
  product blocker was found; the focused 50-test matrix passed.
- Blocker corrections: 3/3 exhausted
- PR and merge: no PR opened; phase blocked and retained as evidence

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Candidate `d536a1e` adds the private resident request/workspace/worker and regular-file relay, extends authenticated direct/HTTP operations, composes global local/remote scheduling and authority lifecycle, and keeps resident paths agent-local. |
| Tests added or updated | Unit and integration coverage exercises hard-cutover codecs, path/link/size/digest rejection, delivery, transfer, process, restart/outage, authority, result, and release behavior; the missing causal case is a crash after final file publication but before SQLite commit. |
| Validated revision/tree state and evidence | `make validate-pr` passed 2,435 default and 141 configuration-extra tests with 3 expected skips plus builds; fresh categorized summary recorded 2,576 passes; required review's focused matrix passed 50 tests. |
| Validation-relevant changes after evidence | Roadmap status/evidence metadata only. |
| PR, review, and merge | Required review found the transfer-finalization crash-replay blocker; no PR opened and no merge attempted. |
| Residual risk and cleanup | A crash after verified publication but before transfer-row commit can strand input before grant or output before terminal commit. Correction 3/3 is exhausted; branch/worktree retained as read-only evidence and Phase 5A owns the narrow closure. |
