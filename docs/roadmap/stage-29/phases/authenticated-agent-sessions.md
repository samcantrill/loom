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
  reconcile journal identity, publish bounded CPU/memory inventory and
  availability offers, and hold one long-poll work request. The coordinator can
  authenticate and authorize clients and operators over the same application
  boundary. No remote assignment, artifact byte, or process launch is possible
  in this phase.
- Earlier dependency: Phase 3 proves application operations and authorization
  locally. This phase adds transport-derived identity and remote session state;
  it must not introduce alternative lifecycle or policy owners.
- Later work explicitly out of scope: Phase 5 enables CPU/memory assignment,
  artifact relay, and remote launch only after this transport gate passes. Phase
  6 adds GPU offers/claims and preferences. Phases 7–8 add controls and recovery.

The no-launch boundary is intentional. It allows Loom to validate network
reachability, certificate/service identity, role mapping, request bounds,
session revisions, and pool authorization before a remote peer can execute code
or move artifacts.

## Current Source And Harness

- Reuse Phase 3 client/local-agent/operator application views, shared
  authorizer, direct adapter conformance, coordinator SQLite ownership, safe
  status/errors, and protected configuration patterns.
- Rediscover existing authority HTTP/client codecs, TLS test fixtures,
  idempotency/version envelopes, payload limits, fake clocks/networks, and
  application error normalization.
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
  coordinator ID/generation, verified peer role, and bounded supported
  capabilities. It performs no admission, offer, assignment, or control
  mutation and exposes no paths, process details, config contents, or broad
  unauthenticated health data.
- Require mutual TLS for persistent HTTP. Verify the expected coordinator
  service identity on agents and configured client/agent/operator principals on
  the coordinator. Require TLS 1.2 or newer with TLS 1.3 available where the
  platform supports it; disable TLS early data for mutations; do not follow
  redirects across service identity.
- Map certificate/transport identity to one configured stable principal. Keep
  credential ID, principal, role, agent ID, session ID, and coordinator
  ID/generation distinct. Certificate subject text and body/path actor values do
  not directly grant identity or authorization.
- Apply per-operation authorization after authentication. Check role, action,
  run/object, pool, agent, and session scope from current coordinator policy.
  Authentication alone grants no method.
- Keep direct and HTTP behavior conformant. A direct adapter supplies a trusted
  principal captured at construction; an HTTP adapter derives the principal
  from verified transport. Both normalize to the same request values,
  authorizer, idempotency logic, store transitions, limits, errors, and audit.
- Add agent registration policy mapping an authenticated agent principal to one
  stable agent ID, allowed pools, allowed project/environment/executor
  capabilities, permitted resource contracts, and credential IDs. Intersect
  this policy with trusted local daemon declarations; an offer cannot create an
  agent, pool, or capability.
- Add durable agent session and offer identities:

  ```text
  coordinator_id + coordinator_generation
  agent_id + agent_session_id
  config_revision
  inventory_revision
  availability_revision
  offer_id + receipt_time + expiry
  work_request_id
  ```

  A reconnect resumes the same session only when durable identity and expected
  revisions agree. Connectivity loss does not create a new session or retire
  old work.
- Add safe CPU/memory offer projection. Inventory reports configured manageable
  capacity and safe project/environment/executor/resource-contract
  fingerprints; availability reports exact net remaining capacity and the live
  claim identities already reflected. Offers contain no commands, host paths,
  URLs, credentials, provider tokens, raw hardware handles, or unsafe exception
  text.
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
  bytes, granting or starting a process, or changing authority lifecycle.
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
- One coordinator generation is authoritative. A copied database/key used by
  two live coordinators is unsupported split brain and must not be presented as
  high availability.

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
Every mutation also checks expected generation/session/revision and
digest-bound idempotency. TLS secrecy and peer authentication do not replace
those lifecycle checks.

### Session and reconnect

An agent starts or reconnects in this order:

```text
authenticate coordinator service identity
  -> no-mutation capability handshake
  -> authenticate agent principal and register/resume session
  -> reconcile durable event/outbox/session facts
  -> publish fresh inventory and zero/current availability as appropriate
  -> issue one revision-bound work request
```

A new TCP connection is transport only. It does not change session identity,
acknowledge events, create availability, or imply that previous work stopped.

### Idempotency receipt

The durable key is conceptually:

```text
(principal_id, operation, idempotency_key)
    -> canonical_request_digest + recorded_result + lifecycle/expiry state
```

Receipts for operations that can still influence current state cannot be simply
deleted. Retention may compact them to a terminal/expired tombstone that rejects
reuse but contains no secret payload.

### Transport configuration

Examples may use names such as:

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

### Private discretion

HTTP framework selection within existing dependencies, route layout, certificate
parser helpers, connection pooling, and polling implementation remain private.
The executor may not weaken derived identity, scoped authorization, bounded
decoding, idempotency, or the no-launch gate.

## Proportionality

- Reuses Phase 3 application views/authorizer and existing HTTP/TLS/codec test
  patterns.
- Adds only the remote identity/session/offer boundary needed to test network
  communication before execution.
- Defers data plane, GPU, control, PKI automation, and HA. This makes the first
  remote PR security-reviewable and reversible without remote code side effects.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Peer identity comes from verified transport | TLS adapter/principal map | Body/path actor or wrong certificate | Unauthorized execution/control | Certificate/service/body mismatch matrix |
| Authentication is not authorization | Application authorizer | Valid but over-scoped principal | Cross-run/pool mutation | Role/action/object/pool matrix |
| Replay cannot change intent | Idempotency store | Duplicate/reordered request | Repeated mutation | Same/different digest and pruning tests |
| Reconnect does not replace session | Session store | New connection or stale daemon | Lost/duplicated ownership | Reconnect/generation/revision tests |
| Pool membership is coordinator policy | Registration policy | Agent offer text | Self-authorized capacity | Allowed/intersection/denied pool tests |
| One delivery-active request per session/revision | Work-request owner | Concurrent/stale polls | Duplicate delivery | Barrier and supersession tests |
| Offer data is safe and bounded | Offer codec/projector | Agent observation/error | Secret leak/resource abuse | Field allowlist, oversize, redaction tests |
| Phase 4 cannot launch or transfer | Capability/application gate | Accidental route enablement | Premature remote side effect | Launcher/artifact sentinels in all remote tests |

## Implementation Slices

1. Add TLS/service-identity configuration and capability handshake, principal
   mapping, HTTP adapters for scoped application views, bounded codecs, and
   direct/HTTP conformance with the negative authentication/authorization matrix.
2. Add durable coordinator generation, agent registration/session/reconcile,
   principal/content-bound idempotency, receipt retention/tombstones, and safe
   audit/status with restart/replay/version tests.
3. Add CPU/memory inventory and availability offers, coordinator-controlled
   pool mapping, one cross-pool availability identity, offer TTL/revisions, and
   one delivery-active long-poll request that can return only wait.
4. Add protected deployment/overlap-rotation documentation, worker-environment
   credential exclusion, loopback E2E, and opt-in `machine-A`/`machine-B`
   no-mutation connectivity receipt.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Transport remains outside domain/scheduling imports | Import boundaries and optional configuration behavior |
| Unit | Required | Codecs, limits, principal map, idempotency, sessions/offers | Boundary values, downgrade, duplicate keys, safe errors, TTL/revisions |
| Contract | Required | Direct/HTTP semantic equivalence | Identical authz/state/idempotency/error outcomes for each operation |
| Integration | Required | Real TLS loopback and durable reconnect | Wrong CA/service/role/scope; restart/replay; stale poll; one pool domain |
| E2E / opt-in | Required loopback; optional two-machine | No-mutation connectivity | Authenticated register/offer/wait on loopback; abstract two-machine receipt when credentials exist; launch/artifact sentinels untouched |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: trusting network location or body identity; broad service
  interface; replay after receipt pruning; stale session delivery; credentials
  in logs/worker env; accidentally enabling launch before the gate passes.
- Review focus: TLS verification, role/scope table, derived identity, request
  limits, idempotency persistence, session revisions, offer safety, and negative
  no-side-effect evidence.
- Stop if: the existing HTTP stack cannot enforce mutual peer/service identity;
  principal mapping would depend on body fields; session state cannot survive
  restart; local/direct behavior diverges; or the transport cannot guarantee no
  remote assignment during this phase.
- Accepted debt: credential provisioning and internet-facing hardening are
  deployment concerns outside Stage 29; coordinator generation is not HA.

## Executor Handoff

- Read this file, Phase 3 completion record, manifest security constraints, and
  planning FR-11, FR-17, FR-19, FR-20, FR-25, and FR-26.
- Complete loopback negative/conformance gates before the optional two-machine
  receipt. Never require site credentials in default CI.
- Decisions not to revisit: outbound agents, mTLS plus scoped authorization,
  derived principal, distinct session/generation identities, one pool-backed
  availability domain, bounded messages, and no launch/data in Phase 4.
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
