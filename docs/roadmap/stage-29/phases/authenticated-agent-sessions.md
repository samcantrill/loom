# Phase 4 Execution Plan: Authenticated Agent Sessions

## Metadata

- Status: `in_progress`
- Stage/phase: Stage 29, Phase 4
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p4-authenticated-agent-sessions`
- Base: clean `origin/develop` `ad3c8349f014f454c831d6e3f50cf97cec3ddea5`
- PR: `feat(protocols): add authenticated agent sessions` into `develop`
- Dependency: Phase 3D merged as PR #237 (`6a8cf9f`)
- Route: expanded planning and independent PR review because this phase creates
  the remote identity, authorization, and durable-session boundary.

## Objective And Boundary

Prove that an outbound agent can authenticate the coordinator, register or
resume its coordinator-issued durable session, publish bounded CPU/memory
availability, and hold one revision-bound work request over real loopback mTLS.
Expose the existing client and operator operations through the same authenticated
application boundary. Agent operations in this phase return only protocol facts
or `wait`: they cannot create or bind an assignment, access artifacts, grant an
attempt, or invoke a launcher. Phase 5 owns remote delivery, transfer, event
replay for assigned work, and execution.

## Current Source And Harness

- `loom.queue.local_daemon` is the application and durable coordinator owner. It
  has stable coordinator/root identity, a rotating process epoch, direct
  client/operator views, and only `_require_role`; it has no agent view, scoped
  policy authorizer, credential map, session records, or remote offers.
- `loom.queue.local_daemon_transport` is owner-only Unix IPC. It derives the
  local UID and serves the client view with bounded JSON; it is not TLS and must
  remain supported with unchanged local client behavior.
- `loom.pipeline.execution.managed_local` owns assignment/provider/journal facts
  and the coordinator offer shape used by current local execution. Phase 4 may
  reuse validated CPU/memory value shapes, but remote offers must not enter that
  scheduling/assignment path before Phase 5.
- `loom.authority.app` and `loom.pipeline.stores.authority_client` supply only
  HTTP/plain-data implementation patterns. The authority service is a distinct
  trust boundary and does not supply an agent view, peer extraction, or a shared
  coordinator authorizer.
- The focused baseline is 209 passes plus
  `test_live_control_substitution_rejects_cached_coordinator_identity` failing
  because live substitution produced the equally fail-closed
  `coordinator control state is unavailable` rather than the expected
  `control identity is invalid`. Resolve that diagnostic/test mismatch before
  the Phase 4 gate without weakening stable-root binding or broadening scope.
  The repository has no existing TLS certificate fixture.

## Fixed Contracts

### Identity and current authorization

Phase 4 adds the missing coordinator-owned agent view and scoped authorization
service; it does not claim Phase 3 already supplied them. The HTTP adapter first
completes TLS peer and expected-service verification, derives a configured
credential ID from that verified connection, resolves it to one stable
principal, then bounded-decodes and authorizes the operation. Request body,
path, certificate subject text, network address, connection ID, agent ID, and
session ID cannot select or override the principal.

Persistent HTTP requires mutual TLS 1.2 or newer. The agent verifies the
configured coordinator service identity; the coordinator verifies an accepted
client certificate. Mutations do not use early data, and clients do not follow
redirects across service identity. The authenticated, non-mutating handshake
returns only protocol/capability versions, stable coordinator ID, current epoch,
and the caller's verified role; it exposes no paths, configuration, or broad
unauthenticated health data.

Every operation and long-poll renewal rechecks the connection credential against
the current policy revision, then checks role, action, object/run, pool, agent,
and session scope as applicable. Authentication alone grants no method. Removing
a credential fences later operations on an existing connection; an overlapping
credential for the same principal may resume after reconciliation. Credential
removal neither retires a session nor proves process containment.

Direct views capture a trusted principal at construction and use the same
authorizer and domain transitions as HTTP. Replace the narrow role check behind
existing client/operator views as needed, while preserving their observable
permissions and owner-only Unix path. Agent, client, and operator credentials
cannot call the authority application, and authority credentials cannot enter
protocol payloads, offers, audit, or worker environments. Exact modules, helper
types, route layout, HTTP framework, and certificate parsing remain private;
do not add a root public import unless a current external consumer requires it.

### Durable session and offers

The existing coordinator root remains authoritative for stable
`coordinator_id`, current `coordinator_epoch`, policy revision, accepted receipt
time, idempotency results, remote sessions, offers, and delivery-active poll.
The protected agent root owns stable agent identity, the registration operation
ID and canonical digest persisted before send, the returned session persisted
before offer, and reconciliation state. Preserve all valid Phase 3 admissions
and root bindings across any additive durable-format change; do not reinitialize
or reinterpret a current root. The earlier fresh-only managed-local cut-over is
unchanged.

The coordinator allocates the opaque session ID in an idempotent registration
transaction. Exact replay returns it; caller-selected IDs conflict. Reconnect
resumes only the same `(coordinator_id, agent_id, session_id)` with expected
coordinator epoch, config, inventory, availability, and policy revisions.
Connection loss changes none of those facts. After coordinator restart, the
stable ID matches, the epoch rotates, and reconciliation plus a fresh
current-epoch offer and poll are required.

A new session is allowed initially, or after the authenticated old session
withdraws its offer, fences its poll, and both durable owners prove the complete
known assignment/provider/delivery/control/transfer/result/output/event/outbox
reference set empty. Commit `RETIRED_CLEAN` and a rejecting tombstone atomically
with rollover. Lost old journal, unresolved reference, expiry, new connection,
or credential rotation cannot retire it; Phase 9 owns guarded replacement.

Registration policy maps principal to stable agent ID and allowed pools,
resident project/environment/executor capabilities, and resource contracts.
Effective capabilities are the intersection with trusted agent declarations.
One inventory/availability identity backs every authorized pool view. Offers
carry bounded safe descriptors, exact CPU/memory capacity atoms, config/
inventory/availability revisions, reflected live-claim IDs, and expiry from
coordinator-accepted time; they carry no paths, commands, URLs, credentials,
provider handles, or raw errors. One current poll per session/availability
revision deterministically supersedes or conflicts with an older poll.

Mutations bind `(principal, operation, idempotency key)` to a canonical digest
and durable result. Changed-content reuse conflicts; actionable receipts remain
or become non-reusable tombstones. Timeout, disconnect, cancellation, or 5xx
after send is indeterminate and retries the same identity. Unknown protocol
versions, methods/content types, duplicate keys, non-finite numbers, or exceeded
body/depth/identifier/collection/offer/poll/deadline limits fail before mutation.

### No-launch gate and compatibility

The agent view owns only handshake, register/resume/clean-retire, reconcile
session identity, publish offer, and wait-only work request. Phase 4 remote
offers are retained protocol state but are ineligible to the current scheduling
kernel and assignment store. Agent requests cannot call client admission or
cancellation, operator reconciliation, authority mutation, assignment
reservation/bind/grant, artifact access, provider preparation, or launcher
owners. Existing client submission/cancellation may retain Phase 3 effects;
that does not weaken this agent-operation boundary.

## Implementation Slices

1. Add protected endpoint/trust/principal-policy configuration, the shared
   scoped authorizer, agent view, bounded protocol values, and direct/HTTP
   adapters. Keep the Unix client route and authority boundary intact.
2. Add coordinator- and agent-owned durable registration/replay/session/
   retirement state, current-policy checks, safe audit/status, and restart
   reconciliation. Correct the localized baseline diagnostic mismatch while
   retaining fail-closed live-store substitution.
3. Add safe CPU/memory offer projection and wait-only polling, then the real
   loopback mTLS harness. Deployment names, storage layout, polling mechanism,
   and optional two-machine receipt format are implementation choices within
   the contracts above.

## Test And Validation Plan

Required focused evidence:

- unit tests for bounded codecs, identity distinctions, current-policy removal,
  digest replay/conflict, restart epochs, coordinator-issued session replay,
  clean-retirement refusal/tombstone, offer limits/TTL, and stale poll handling;
- contract tests proving direct/HTTP parity for authorization, state,
  idempotency, safe errors, and definite versus indeterminate outcomes;
- integration tests using a real TLS 1.2+ loopback connection for valid peers,
  wrong CA/service/client role, body-identity mismatch, credential overlap and
  removal on a live connection/poll, restart/re-offer, lost registration
  response, concurrent polls, and absence of an inbound agent listener; and
- causal no-launch tests around every agent operation: snapshot or spy the
  authority, assignment/reservation, local offer eligibility, provider,
  artifact, and launcher owners and prove none changed or ran. A response that
  merely contains no assignment is insufficient.

Run the focused queue/unit/contract/integration/E2E suites, then
`make validate-pr` and `make test-summary`. Default CI must create its own
loopback credentials without a heavyweight runtime dependency. A protected
`machine-A`/`machine-B` connectivity receipt is optional and must contain only
role, protocol/capability versions, safe result code, and time.

## Risks And Stops

Review transport peer extraction and expected-service verification, current
scope checks, root/schema continuity, coordinator-issued session identity,
retirement completeness, offer ineligibility, indeterminate replay, safe
diagnostics, and causal no-launch evidence. Stop without implementation if the
available server stack cannot expose verified peer identity; identity would
depend on request data; existing valid Phase 3 durable state cannot be preserved
without reopening migration policy; agent and authority/application ownership
would merge; local/direct semantics would diverge; a new runtime dependency is
required; or an agent operation can reach assignment, artifact, provider, or
launch state. Escalate changes to the accepted trust model, durable identity,
compatibility, dependency ownership, or Phase 4/5 boundary.

## Executor Handoff

Implement only the three slices above. Treat outbound agents, transport-derived
identity, current per-operation scope, coordinator-issued durable sessions,
cooperative-empty rollover, one cross-pool availability domain, indeterminate
replay, and the no-launch/data boundary as fixed. Complete automated loopback
and negative gates before any optional site receipt; site credentials are never
a default-CI prerequisite.

## Workflow State

- Manager preparation: complete at `051c009`; Phase 3D dependency, current
  source seams, branch/worktree, target/title, baseline anomaly, and gates are
  recorded.
- Expanded planning: complete; stale Phase 3 agent-view/shared-authorizer/TLS
  assumptions removed and the executor packet reduced around current owners.
- Implementation, pre-submit gate, required independent review, PR, and merge:
  pending. Refiner not used; blocker corrections `0/3`.

## Completion Record

Implementation paths, tests, validation revision/evidence, PR/review/merge, and
residual risk remain pending.
