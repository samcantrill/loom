# Phase 4 Execution Plan: Authenticated Agent Sessions

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 4
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p4-authenticated-agent-sessions`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 3 remotely merges
- PR target: `develop`
- PR title: `feat(protocols): add authenticated agent sessions`
- Dependencies: Phase 3 merged with one coordinator application owner, narrow
  role views, authorizer, persistent state, and local daemon composition
- Workflow path: expanded because this phase establishes the remote trust,
  authorization, replay, and session boundary before remote code execution
- Blockers: Phase 3 remote merge and opt-in site credentials for the optional
  two-machine receipt; automated loopback evidence must not depend on them

## Objective And Context

- Vertical outcome: outbound daemons on `machine-A` and `machine-B` can
  authenticate a coordinator, establish or resume an authorized agent session,
  safely retire an empty old session, reconcile journal identity, publish bounded CPU/memory inventory and
  availability offers, and hold one long-poll work request. The coordinator can
  authenticate and authorize clients and operators over the same application
  boundary. No remote assignment, artifact byte, or process launch is possible
  in this phase.
- Earlier dependency: Phase 3 proves application operations and authorization
  locally. This phase adds transport-derived identity and remote session state;
  it must not introduce alternative lifecycle or policy owners.
- Later work explicitly out of scope: Phase 5 enables CPU/memory assignment,
  artifact relay, and remote launch only after this transport gate passes. Phase
  6 adds GPU offers/claims and preferences. Phase 7 adds the separate restricted
  SLURM-bootstrap application view, Phase 8 adds controls, and Phase 9 adds
  recovery.

The no-launch boundary is intentional. It allows Loom to validate network
reachability, certificate/service identity, role mapping, request bounds,
session revisions, and pool authorization before a remote peer can execute code
or move artifacts.

Existing client submission and cancellation operations still invoke their Phase
3 semantics and may mutate admitted-run/authority state. The Phase 4 gate is
specifically that agent-session, offer, and work-request operations cannot
prepare, bind, grant, transfer, or launch remote stage execution.

## Current Source And Harness

- Reuse Phase 3 client/local-agent/operator application views, shared
  authorizer, authenticated scoped coordinator-authority adapter, direct adapter
  conformance, coordinator SQLite ownership, safe status/errors, and protected
  configuration patterns.
- Rediscover existing authority HTTP/client codecs, service test utilities,
  idempotency/version envelopes, payload limits, fake clocks/networks, and
  application error normalization. Add or extend the real TLS fixtures and
  verification harness needed here; the pre-Stage-29 source does not already
  provide them, though Phase 3 may have introduced a bounded local subset if it
  selected HTTP instead of owner-only IPC.
- Standard-library/existing HTTP dependencies are preferred. Do not add a
  broker, service mesh, streaming platform, certificate authority, or
  heavyweight networking dependency.
- Automated tests use loopback and fake transports. Real `machine-A`/
  `machine-B` connectivity is an explicit opt-in receipt and performs no run,
  assignment, artifact, or launch mutation.

## Scope

In scope:

- Add versioned plain-data HTTP operations for a minimal capability handshake,
  client submission/status/cancellation surface, agent registration/session
  reconciliation, critical-event replay acknowledgement, inventory/availability
  offer publication, and one revision-bound long-poll work request.
- The handshake authenticates both peers and returns only protocol version,
  stable coordinator ID/current process epoch, verified peer role, and bounded
  supported capabilities. It performs no admission, offer, assignment, or control
  mutation and exposes no paths, process details, config contents, or broad
  unauthenticated health data.
- Require mutual TLS for persistent HTTP. Verify the expected coordinator
  service identity on agents and configured client/agent/operator principals on
  the coordinator. Require TLS 1.2 or newer with TLS 1.3 available where the
  platform supports it; disable TLS early data for mutations; do not follow
  redirects across service identity.
- Map certificate/transport identity to one configured stable principal. Keep
  credential ID, principal, role, stable agent ID, durable session ID, stable
  coordinator ID, coordinator process epoch, and connection ID distinct.
  Certificate subject text and body/path actor values do not directly grant
  identity or authorization.
- Recheck the connection-derived credential against the current principal-policy
  revision on every operation and long-poll renewal. Removing a credential
  fences future protocol operations even on an established connection, but does
  not retire its durable session, cancel a granted assignment, or prove process
  containment. An overlapping credential mapped to the same principal may
  resume the same session after reconciliation.
- Apply per-operation authorization after authentication. Check role, action,
  run/object, pool, agent, and session scope from current coordinator policy.
  Authentication alone grants no method.
- Keep direct and HTTP behavior conformant. A direct adapter supplies a trusted
  principal captured at construction; an HTTP adapter derives the principal
  from verified transport. Both normalize to the same request values,
  authorizer, idempotency logic, store transitions, limits, errors, and audit.
- Reuse the Phase 3 peer/service-identity and authorization primitives for
  transport consistency, but keep the authority view distinct from client,
  agent, and operator views. Agent/client/operator certificates cannot call
  authority operations, and authority/coordinator credentials never enter an
  offer, work request, response, audit payload, or future worker environment.
- Add agent registration policy mapping an authenticated agent principal to one
  stable agent ID, allowed pools, allowed project/environment/executor
  capabilities, permitted resource contracts, and credential IDs. Intersect
  this policy with trusted local daemon declarations; an offer cannot create an
  agent, pool, or capability.
- Add durable agent session and offer identities:

  ```text
  coordinator_id + coordinator_epoch
  agent_id + agent_session_id
  config_revision
  inventory_revision
  availability_revision
  offer_id + coordinator_accepted_receipt_time + expiry
  work_request_id
  ```

  A reconnect resumes the same session only when durable identity and expected
  revisions agree. Connectivity loss does not create a new session or retire
  old work. A coordinator restart keeps `coordinator_id` and rotates only its
  process epoch after reopening/reconciling the same state root.
- The coordinator, not a request body, allocates an opaque session ID in the
  idempotent registration/rollover transaction. The agent journals that
  operation ID and canonical digest before send, so a crash or lost registration
  response replays and returns the same recorded ID; the agent journals the
  returned session before publishing an offer. A caller-proposed or copied
  session ID cannot become current.
- Permit a clean new agent session only through authenticated cooperative
  retirement of the old session: fence its delivery-active connection, withdraw
  its offer, reconcile both journals, and prove the complete assignment,
  provider preparation/claim, delivery/work-request, control, transfer,
  result/output, sequenced-event, and outbox reference set is empty before one
  coordinator transaction records `RETIRED_CLEAN` and a tombstone. Initial registration is
  allowed when no prior session exists. If old state is lost/unavailable or any
  reference is unresolved, reject the new session until Phase 9 positive-
  containment replacement. Offer expiry, a new connection, or credential
  rotation alone is never session retirement.
- Add safe CPU/memory offer projection. Inventory reports configured manageable
  capacity and safe project/environment/executor/resource-contract
  fingerprints; availability reports exact net remaining capacity and the live
  claim identities already reflected. Offers contain no commands, host paths,
  URLs, credentials, provider tokens, raw hardware handles, or unsafe exception
  text. Expiry uses coordinator-accepted receipt time. After a coordinator
  process-epoch change, session reconciliation and a newly received current-
  epoch offer/work request are required before delivery; a retained old offer
  cannot authorize a new assignment.
- Back all authorized pool views for one agent with one inventory/availability
  domain and exact capacity keys. Pool membership comes from coordinator policy
  intersection. This phase does not reserve capacity, but its schema must make
  later double counting impossible.
- Permit one delivery-active connection/long poll per agent session and
  availability revision. A newer authenticated request supersedes or conflicts
  with an older delivery channel deterministically; stale channels cannot
  receive future work. Phase 4 replies with wait/no-delivery only.
- Bind mutation idempotency to principal, operation, idempotency key, and
  canonical request digest. Exact replay returns the recorded result; reuse with
  different content conflicts. Retain actionable receipts or terminal/expired
  tombstones long enough that pruning cannot make a replay actionable again.
- Wire the Phase 2 critical-event stream with stable event IDs and monotonic
  per-assignment sequence. Accept only the next expected sequence or exact
  replay; return a typed gap response without advancing later facts. An
  acknowledgement names only an event/contiguous range durably committed by the
  coordinator, so the agent retains unacknowledged outbox rows.
- Classify a transport timeout, disconnect, caller cancellation, or 5xx after
  send as indeterminate. The caller retries the same principal/operation/key/
  digest and waits for the recorded domain result or conflict. Connection close
  never rolls back or cancels a server mutation; only explicit cancellation is
  a domain operation.
- Enforce expected method, service host/identity, content type, protocol/schema
  version, duplicate-key rejection, finite numeric forms, and strict limits for
  body size/depth, identifiers, collections, offers, capabilities, concurrent
  polls, per-principal admission, idempotency records, audit facts, and read/
  idle deadlines. Unknown/downgraded versions fail before mutation.
- Produce allowlisted, bounded audit/status facts using safe error codes and
  object identities appropriate to the caller. Do not return raw exception
  strings, stack traces, commands, paths, tokens, certificate subjects, or
  provider-private data.
- Add protected deployment configuration using abstract endpoint and secret
  references. Environment variables may point to the coordinator endpoint,
  trust bundle, certificate/key files, and principal-policy configuration; do
  not put private key material in authored job config, committed `.env` files,
  request bodies, durable job rows, or worker environments.
- Support initial credential rotation through configured overlapping accepted
  credentials. Removing a credential prevents future authentication but does
  not prove process containment or retire a session by itself.
- Add a loopback conformance suite and an opt-in `machine-A`/`machine-B`
  connectivity command/receipt. The receipt records only safe endpoint role,
  protocol/capability versions, success/failure code, and time; it never records
  key material or full certificate details.

Out of scope:

- Returning an assignment from a work request, transferring request/input/output
  bytes, granting or starting a process, or allowing an agent transport operation
  to change stage-attempt/assignment lifecycle. Existing authorized client run
  admission/cancellation remains in scope through the Phase 3 application view.
- GPU/device inventory and placement, remote controls, cancellation delivery,
  session takeover, artifact URLs, peer-to-peer agents, broker infrastructure,
  internet-facing hosting, or coordinator HA.
- Credential issuance/PKI automation, identity federation, application-layer
  signatures, at-rest encryption/key management, hostile-code sandboxing, or
  treating TLS as process fencing.

Assumptions:

- Deployments can provision a private trust relationship and protect private
  key/config file permissions under the user's account.
- Network messages are untrusted even on an internal network. Authored local
  daemon configuration remains trusted deployment state.
- One stable coordinator identity and one current process epoch are
  authoritative for a durable root. A copied database/key used by two live
  coordinators is unsupported split brain and must not be presented as high
  availability.

## Fixed Contracts And Private Discretion

### Authentication versus authorization

The application order is fixed:

```python
peer = tls_adapter.authenticate(connection)
principal = principal_map.resolve(peer.credential_id)
request = codec.decode_bounded(body)

authorizer.require(
    principal=principal,
    action=request.operation,
    object_ref=request.object_ref,
    pool=request.pool,
    agent_session=request.agent_session,
)

return application.apply(request, principal=principal)
```

Decoding validates inert data; it cannot load code or override `principal`.
Every mutation also checks its expected coordinator process epoch, agent
session, object revision, current credential-policy revision, and digest-bound
idempotency. TLS secrecy and peer authentication do not replace those lifecycle
checks.

### Session and reconnect

The remote topology is outbound-only. The coordinator exposes authenticated
client, agent, and operator views; an agent opens the connection and never
listens for coordinator callbacks. Agents do not discover or contact peers. A
long poll is a coordinator-addressed delivery channel, not permission for the
agent to choose a queue item.

An agent starts or reconnects in this order:

```text
authenticate coordinator service identity
  -> no-mutation capability handshake
  -> authenticate agent principal and register/resume session
  -> reconcile durable ordered event/outbox/session facts
  -> publish fresh inventory and zero/current availability as appropriate
  -> issue one revision-bound work request
```

A new TCP connection is transport only. It does not change session identity,
acknowledge events, create availability, or imply that previous work stopped.

No inter-service startup order is required after explicit role-root bootstrap:

- an agent started before the coordinator opens its existing journal at zero
  availability and reconnects with bounded backoff;
- a coordinator started without this agent retains admissions/work but sees no
  capacity from it;
- after coordinator restart the stable coordinator ID must match, the process
  epoch changes, and the agent must reconcile and publish a fresh current-epoch
  offer/work request before delivery; and
- a client request while the coordinator is down receives unavailability and
  reuses its exact idempotency identity if delivery was ambiguous.

Authority then coordinator then agents is the recommended operational order
only because it minimizes degraded intervals. It is not a safety dependency.

Clean rollover is a separate transition initiated by the authenticated old
session after complete reconciliation. The coordinator allocates the new
session identity; the request does not choose it:

```text
withdraw offer and fence delivery channel
  -> coordinator and old journal both report empty unresolved set
  -> commit RETIRED_CLEAN + old-session tombstone
  -> idempotently allocate/register new session at zero availability
```

A newly installed daemon with no old journal cannot assert that proof. It uses
the Phase 9 replacement path if the coordinator retains any old-session fact.

### Idempotency receipt

The durable key is conceptually:

```text
(principal_id, operation, idempotency_key)
    -> canonical_request_digest + recorded_result + lifecycle/expiry state
```

Receipts for operations that can still influence current state cannot be simply
deleted. Retention may compact them to a terminal/expired tombstone that rejects
reuse but contains no secret payload.

An HTTP status is not itself a lifecycle outcome. A definite decoded domain
result such as `DENIED`, `INVALID`, `CONFLICT`, or recorded success may be acted
on. Timeout/unavailable after send remains `OUTCOME_UNKNOWN` and is reconciled
with the same idempotency identity.

### Transport configuration

Protected deployment configuration must contain enough information for each
role to verify, rather than merely locate, its peer. Conceptually:

```yaml
coordinator:
  local_state_root: <protected-local-root>
  listen_endpoint: <coordinator-endpoint>
  tls_server_identity: <certificate-and-key-references>
  principal_policy: <policy-reference>

agent:
  local_state_root: <protected-local-root>
  stable_agent_id: machine-A
  coordinator_endpoint: <coordinator-endpoint>
  expected_coordinator_identity: <service-identity>
  tls_client_identity: <certificate-and-key-references>
  declared_pools: [research]
  manageable_resources: <provider-backed-inventory>
```

The coordinator policy maps the authenticated agent principal to the stable
agent ID, allowed pools, resident capabilities, and resource contracts; the
effective offer is the intersection with trusted local declarations. Neither
the body nor certificate subject text creates those permissions. The
coordinator, not deployment config or the request, allocates the durable session
ID.

Examples may use environment-reference names such as:

```text
LOOM_COORDINATOR_ENDPOINT
LOOM_TLS_CA_FILE
LOOM_TLS_CERT_FILE
LOOM_TLS_KEY_FILE
LOOM_PRINCIPAL_POLICY_FILE
```

Names remain deployment-facing decisions during implementation. Values are
protected process configuration, not job configuration. Logs/status show only
whether a value is configured and a safe credential ID where authorized.
Endpoint and non-secret values may be supplied by protected config/environment
references, but private key material must not be committed in `.env` or copied
into queue rows, offers, assignment payloads, audit output, or worker
environments.

### Private discretion

HTTP framework selection within existing dependencies, route layout, certificate
parser helpers, connection pooling, and polling implementation remain private.
The executor may not weaken derived identity, scoped authorization, bounded
decoding, idempotency, or the no-launch gate.

## Proportionality

- Reuses Phase 3 application views/authorizer and current HTTP/codec/service
  patterns; this phase completes the TLS harness required for remote peers.
- Adds only the remote identity/session/offer boundary needed to test network
  communication before execution.
- Defers data plane, GPU, control, PKI automation, and HA. This makes the first
  remote PR security-reviewable and reversible without remote code side effects.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Peer identity comes from verified transport | TLS adapter/principal map | Body/path actor or wrong certificate | Unauthorized execution/control | Certificate/service/body mismatch matrix |
| Authentication is not authorization | Application authorizer | Valid but over-scoped principal | Cross-run/pool mutation | Role/action/object/pool matrix |
| Credential policy is current per operation | Application authorizer | Removed credential on an established connection/long poll | Continued unauthorized mutation after rotation | Policy-revision removal, poll renewal, overlapping-credential resume tests |
| Replay cannot change intent | Idempotency store | Duplicate/reordered request | Repeated mutation | Same/different digest and pruning tests |
| Reconnect does not replace session and request bodies do not allocate it | Agent registration journal + coordinator session store | Crash/lost registration response, caller-proposed ID, new connection, or stale daemon | Lost/duplicated ownership | Pre-send operation persistence, idempotent coordinator-issued ID, and reconnect/generation/revision tests |
| Stable coordinator identity is not its process epoch | Coordinator identity/session handshake | Coordinator restart or stale connection | Valid retained facts rejected or stale process made current | Same-ID/new-epoch and stale-current-operation tests |
| Clean session rollover proves the full extensible reference set empty | Session retirement transaction | New install, credential change, offer expiry, or a later phase adding a reference kind without extending retirement | Orphan live work/capacity | Assignment/provider/delivery/control/transfer/result/event/outbox empty success, unresolved/lost-journal rejection, and late-old-message tombstone tests |
| Critical event acknowledgement is causal and durable | Agent outbox + coordinator event store | Reorder, gap, restart, or response loss | Missing lifecycle fact or premature deletion | Sequence gap/exact replay/contiguous ack tests |
| Transport loss is indeterminate | Adapter + idempotency store | Timeout/5xx after commit | Duplicate mutation or false rollback | Commit-then-timeout/retry-same-key tests |
| Pool membership is coordinator policy | Registration policy | Agent offer text | Self-authorized capacity | Allowed/intersection/denied pool tests |
| One delivery-active request per session/revision | Work-request owner | Concurrent/stale polls | Duplicate delivery | Barrier and supersession tests |
| Offer data is safe and bounded | Offer codec/projector | Agent observation/error | Secret leak/resource abuse | Field allowlist, oversize, redaction tests |
| Coordinator restart cannot reuse a retained offer | Session/offer reconciler | Process-epoch change before agent reconnect | Assignment from stale availability or time | Retained-offer ineligibility and current-epoch re-offer tests |
| Phase 4 agent operations cannot prepare, assign, launch, or transfer | Capability/application gate | Accidental route enablement | Premature remote execution side effect | Attempt/assignment/launcher/artifact sentinels in all agent-connectivity tests |

## Implementation Slices

1. Add protected coordinator/agent configuration, explicit outbound topology,
   TLS/service-identity configuration and capability handshake, principal
   mapping, HTTP adapters for scoped application views, bounded codecs, and
   direct/HTTP conformance with the negative authentication/authorization matrix.
2. Add durable stable coordinator identity/process epochs, coordinator-issued
   agent registration/session/reconcile, cooperative complete-reference
   retirement/tombstones, principal/
   content-bound idempotency, indeterminate-outcome replay, ordered event
   acknowledgement, and safe audit/status with restart/replay/version tests.
3. Add CPU/memory inventory and availability offers, coordinator-controlled
   pool mapping, one cross-pool availability identity, offer TTL/revisions, and
   one delivery-active long-poll request that can return only wait.
4. Add protected deployment/overlap-rotation and current-policy enforcement documentation, worker-environment
   credential exclusion, loopback E2E, and opt-in `machine-A`/`machine-B`
   no-mutation connectivity receipt.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Transport remains outside domain/scheduling imports | Import boundaries and optional configuration behavior |
| Unit | Required | Codecs, limits, principal map, idempotency, identities/epochs, sessions/offers/events | Boundary values, downgrade, duplicate keys, safe errors, TTL/revisions, pre-send registration operation and coordinator-issued session replay, gap/contiguous ack, clean-retirement complete set |
| Contract | Required | Direct/HTTP semantic equivalence | Identical authz/state/idempotency/definite-versus-indeterminate/error outcomes for each operation |
| Integration | Required | Real TLS loopback, service-order behavior, and durable reconnect/rollover | Agent-before-coordinator bounded reconnect at zero availability; coordinator-without-agent no-capacity wait; wrong CA/service/role/scope; removal on established connection/poll; overlapping-credential same-session resume; authority view inaccessible to agent credentials; same coordinator ID/new epoch rejects retained offer until reconcile/re-offer; crash after persisted registration intent and commit-then-timeout replay to the same session; stale poll; cooperative-empty rollover; unresolved/lost-journal refusal and late-old tombstone; one pool domain; no inbound agent listener |
| E2E / opt-in | Required loopback; optional two-machine | No-mutation connectivity | Authenticated register/offer/wait on loopback; abstract two-machine receipt when credentials exist; launch/artifact sentinels untouched |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: trusting network location or body identity; broad service
  interface; treating a timeout as rollback; accepting event gaps; replay after
  receipt pruning; confusing process epoch with stable owner; caller-selected
  session identity; incomplete retirement reference enumeration; unsafe clean
  session replacement; removed credentials surviving on a live connection;
  stale session delivery; credentials
  in logs/worker env; accidentally enabling launch before the gate passes.
- Review focus: TLS verification, role/scope table, derived identity, request
  limits, idempotency persistence, authority-view isolation, session revisions,
  cooperative retirement/tombstones, event ordering/ack durability, outcome
  classification, offer safety, and negative no-side-effect evidence.
- Stop if: the existing HTTP stack cannot enforce mutual peer/service identity;
  principal mapping would depend on body fields; session state cannot survive
  restart; local/direct behavior diverges; or the transport cannot guarantee no
  remote assignment during this phase.
- Accepted debt: credential provisioning and internet-facing hardening are
  deployment concerns outside Stage 29; a rotating coordinator process epoch
  is not HA or a leadership/fencing service.

## Executor Handoff

- Read this file, Phase 3 completion record, manifest security constraints, and
  planning FR-10, FR-11, FR-16, FR-17, FR-19, FR-20, FR-21, FR-25, FR-26,
  DQ-20, and DQ-22.
- Complete loopback negative/conformance gates before the optional two-machine
  receipt. Never require site credentials in default CI.
- Decisions not to revisit: outbound agents, mTLS plus scoped authorization,
  derived principal, stable identities distinct from process/connection epochs,
  same-session reconnect, cooperative-empty clean rollover otherwise guarded
  replacement, ordered replay, indeterminate transport outcomes, one pool-
  backed availability domain, bounded messages, and no launch/data in Phase 4.
- Escalate any change to trust model, principal scope, durable session identity,
  or external dependency.

## Workflow State

- Manager preparation: pending Phase 3 merge, worktree/base recording, and
  exact transport/test rediscovery
- Expanded planning: required by remote trust boundary; phase plan finalized
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: expected because a mistaken boundary can authorize future
  remote execution; confirm during preparation
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
