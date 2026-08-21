# Phase 2 Execution Plan: Authenticated JIT Multi-Agent Stage Pool

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 2
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p2-jit-multi-agent-pool`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 1 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): add authenticated multi-agent stage pool`
- Dependencies: Phase 1 merged with shared readiness, resolved stage placement,
  pure scheduler, durable stage work/assignment saga, authority execution fence,
  local agent journal/runtime, and common application port
- Workflow path: expanded because remote code execution, mTLS identity, expiring
  offers, GPU claims, artifact streaming, and outage replay interact causally
- Blockers: Phase 1 remote merge

## Objective And Context

- Vertical outcome: a client submits runs to one coordinator from any authorized
  machine; outbound agents on `machine-A` and `machine-B` publish configured and
  available CPU/memory/GPU capacity; the coordinator schedules each ready stage
  on the best feasible agent, securely moves required payloads, and preserves
  truthful lifecycle through network and coordinator interruption.
- Earlier dependency: Phase 1 decides when a stage is ready and proves the
  assignment/grant/worker/finalization trace with one local agent. This phase
  changes transport and number/resource kinds, not those semantics.
- Later work explicitly out of scope: Phase 3 adds drain/reload, cancellation
  reconciliation for disconnected agents, containment-gated manual recovery,
  and different-session replacement.

## Current Source And Harness

- Relevant Phase 1 seams: `loom.scheduling` models/engine/resource registry;
  stage placement resolver; coordinator stage-work/assignment store/service;
  authority bind/unbind/execution-fence CAS; application port/authorizer; local
  agent journal/runtime; artifact hand-off; status and public facades.
- Existing foundations: Stage 27 local GPU inventory/assignment plans/providers,
  artifact backend capability/payload contracts, authority HTTP/client patterns,
  serialization limits, process test helpers, and TLS/application auth fixtures
  found on current `develop`.
- Existing tests and seams: Phase 1 scheduler/saga/daemon E2E; GPU provider and
  acceptance tests; artifact fake-backend/materialization tests; authority
  direct/HTTP conformance; fake clocks/networks/processes; package import tests.
- Import, dependency, or harness constraints: remote adapters may depend on the
  existing HTTP stack but scheduling remains transport-free. Core must not add a
  heavyweight vendor SDK. Required automated evidence uses loopback/fakes;
  real-network/GPU checks are opt-in receipts.

## Scope

In scope:

- Add a versioned agent registration/session protocol and separate persistent
  agent daemon. Agents connect outbound only, reconcile their journal first,
  replay unacknowledged critical events, then publish fresh inventory and
  availability. Coordinator generation, agent/session/config/inventory/
  availability revision, offer receipt time/TTL, and connection identity remain
  distinct. A reconnect never implies a new session.
- Add safe offer projection for configured CPU count, memory bytes, discrete GPU
  instances, model, per-device VRAM bytes, supported allocation mode/provider,
  optional topology attributes, executor capabilities, and resident project/
  environment fingerprints. Availability subtracts live physical claims and is
  versioned separately. Offers contain no host paths, commands, credentials,
  raw vendor handles, or provider tokens.
- Extend the resource-planner registry with the current GPU consumer:
  - exclusive mode selects exact device IDs and treats minimum VRAM as a
    per-device eligibility attribute;
  - VRAM-share mode consumes bytes only on a provider that advertises isolation,
    accounting, granularity, and bind support;
  - provider-defined fractional mode accepts exact normalized fractions only for
    a named compatible provider;
  - unsupported mode/version/granularity/model/topology is hard-ineligible with
    a bounded safe reason. Stage 29 does not infer sharing from free VRAM.
- Add built-in versioned hard specs for exact target, allowed/prohibited agent/
  resource attributes, project/executor/artifact compatibility, and GPU
  requirements. Add built-in soft specs for ordered preferred agents, ordered
  GPU models, resource attributes, packing/fill preference, and explicit wait-
  then-fallback. Site configuration fixes preference tier precedence and score
  bounds; only preferences relevant to a requested resource contribute.
- Construct one immutable bounded global scheduling snapshot from ready stage
  work across admitted runs and all fresh offers. Preserve Phase 1 stage order,
  per-run concurrency, hard-before-soft, tri-state search, and deterministic
  stable-ID tie breaks. Scheduler returns one decision per commit; repeated
  cycles update availability logically before the next choice.
- Use one revision-bound outbound long-poll admission request per availability
  revision. Assignment CAS revalidates exact stage work/readiness binding,
  coordinator generation, agent/session/config/inventory/availability/work
  request, resource contracts/claims, pool/target, and uniqueness. Agents do not
  keep a coordinator-created backlog and may safely decline pre-grant on drift.
- Extend the common application port and add direct/HTTP adapters for client
  submit/status/cancel and agent register/reconcile/replay/offer/work/accept/
  decline/grant/control. Direct and HTTP paths normalize to the same requests,
  authorization decisions, idempotency, state transitions, and safe errors.
- Require mTLS on every persistent HTTP peer. Map verified certificates to
  configured client, agent, or operator principals with least-privilege pool/run
  scopes. Bind message actor to context, validate sizes/schema/version before
  policy, reject role/scope/session/nonce/replay mismatch, and support planned
  certificate rotation without payload identity fallback. Secrets/addresses are
  deployment environment or protected config, never authored run state.
- Implement resident-project execution. Each eligible agent independently
  configures trusted project/environment/executor support and advertises safe
  fingerprints. Assignment refers to an already prepared stage plus versioned
  execution values; it never transports arbitrary shell text or imports code
  selected by a submitted payload. Mismatch is hard-ineligible or pre-grant
  decline, not best-effort execution.
- Implement the first network artifact path as a narrow coordinator relay over
  existing artifact identities/capability records:
  - before grant, the agent downloads the immutable prepared request and every
    required input into assignment-scoped temporary storage, verifies size and
    digest, atomically promotes them locally, journals durability, then accepts;
  - after execution, the agent records a bounded output manifest and retains
    payloads until acknowledged; it uploads resumable bounded chunks or streams
    under the exact assignment/principal scope;
  - coordinator stages uploads, verifies digest/declared artifact identity,
    publishes through the configured coordinator artifact store/backend, and
    returns coordinator/backend-accessible `ArtifactRef`s;
  - authority terminal/output commit uses only those finalized refs. An
    agent-local `file:` URI is never persisted as a remote output reference;
  - interrupted or duplicate transfer is idempotent and cannot expose partial
    content. Cleanup follows commit/ack and explicit retention limits.
- Implement outage behavior: a granted agent has every required input and
  continues supervising/running without coordinator connectivity; it journals
  start/result/containment/output facts and retains outputs. It accepts no new
  work. On coordinator restart/reconnect it authenticates, reconciles current
  fences, replays, finishes artifact publication, and only then advertises fresh
  availability. Downstream stages wait for authority output commit.
- Treat agent loss as capacity/liveness uncertainty only. Ungranted definitive
  decline follows Phase 1 exact unbind. Accepted/granted unreachable work remains
  bound/unknown and is not sent to another agent. Independent work and unrelated
  runs may continue on remaining capacity. Phase 3 owns manual resolution.
- Add safe joined status and diagnostics for dependency wait, ready/order wait,
  unsupported resource/contract, target offline, no known compatible agent,
  current capacity wait, preferred-placement wait, stale offer, bind decline,
  transfer wait/failure, active/disconnected/unknown execution, buffered result,
  and completed output commit. Redact paths, commands, subjects beyond safe IDs,
  credentials, claims unsafe for clients, and unrestricted exception text.
- Add abstract `machine-A`/`machine-B` coordinator/agent configuration examples,
  protected environment-variable references, user-service auto-restart guidance,
  certificate bootstrap/rotation operations, and opt-in connectivity/GPU receipt
  scripts that do not contain real hostnames or paths.

Out of scope:

- Agent-to-agent transfer/mesh, shared-filesystem signalling, direct vendor
  object-store implementation, automatic data-locality replication, arbitrary
  code/project shipment, hostile-code sandboxing, or log aggregation beyond the
  bounded current lifecycle/output need.
- One stage using resources from several agents, gang scheduling, distributed
  training coordination, preemption, fair-share/account quotas, licences with a
  global transactional owner, general topology solver, or cloud provisioning.
- Automatic agent-loss retry/requeue, timeout/PID-based failure, different-
  session takeover, remote reload, or manual containment recovery; Phase 3 owns
  explicit controls/recovery.
- Coordinator active-active/standby HA, peer agents, external consensus, or
  delegated SLURM federation.

Assumptions:

- Coordinator network storage has bounded space for relay staging and each
  agent has bounded assignment/result retention configured before readiness.
- Agents are trusted execution principals running authored project code under
  the user's account; mTLS/application auth prevents unauthorized submission or
  daemon impersonation but is not a sandbox.
- Network interruption is expected; checksum identity, journals, idempotency,
  and explicit fences—not connection lifetime—own correctness.

## Fixed Contracts And Private Discretion

- Observable behavior: if both agents fit a ready stage, deterministic policy
  ranks them. A stage requiring one exclusive 64 GiB GPU cannot use a 12 GiB
  device and may use an 80 GiB device. A GPU-model preference has no score on a
  CPU-only preprocess stage. An exact target never spills while offline.
- Offer contract: coordinator receipt time determines expiry. Stale inventory or
  availability produces no new assignment. A new availability revision is
  required after every accepted/declined request; running claims remain visible.
- Scheduling contract: connection/poll order cannot choose work. Queue/stage
  order is resolved before best placement for that stage. Incomplete search does
  not mutate or masquerade as infeasibility.
- Security contract: authenticated role/scope and registered agent ID come from
  the connection context. Payloads contain versioned data only. Every work,
  artifact, event, and control operation is bound to exact assignment/session/
  generation/idempotency and size limits.
- Grant/outage contract: request and inputs are durable plus physical claim held
  before acceptance/grant. Authority execution fence remains valid without
  coordinator liveness. Agent buffers result/output; no success is exposed and
  no descendant unlocks until finalized refs and authority commit exist.
- Artifact contract: relay does not alter artifact content identity. Temporary
  local refs and upload state are evidence only; final accessible refs own
  downstream materialization. Publish/commit is manifest-last and idempotent.
- Recovery contract: offline accepted work is unknown and retains its exact
  resource/assignment fence. No TTL, replacement offer, coordinator generation,
  or machine restart authorizes duplication.
- Cross-phase contract: Phase 3 may withdraw offers and fence assignments only
  through exact controls/recovery. It cannot weaken authentication, readiness,
  grant, transfer, or unknown-work rules.
- Reproducibility: placement decision persists bounded policy version,
  placement fingerprint, agent/session/offer revisions, safe claims, scores and
  reason IDs. Ephemeral rejected candidate details are not durable history.
- Private choices: HTTP route names, long-poll wake mechanism, chunk size and
  resumable-upload internals, TLS library wiring already allowed by dependencies,
  journal table names, retention implementation, and daemon supervisor examples.

## Proportionality

- Existing seam reused: Phase 1 application port/saga/agent, Stage 27 GPU
  inventory/providers, artifact capability/payload contracts, authority HTTP
  patterns, explicit plugin composition, serialization/redaction, and process
  interruption harnesses.
- Material additions and current justification: remote session/offers for global
  capacity; mTLS/scopes for code execution; GPU planner for the accepted VRAM/
  model consumer; relay for network-only stage inputs/outputs; outbox/replay for
  coordinator outage.
- Optional hardening and future capability deferred: peer transfer, selected
  object-store SDK, content cache/eviction optimizer, log service, scheduler
  pluggability, fair-share, solver, HA, and automatic recovery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only authenticated scoped agents contribute capacity. | TLS edge + authorizer + registration store | forged cert/body agent ID | unauthorized code/capacity | direct/HTTP negative matrix |
| Offer inventory and availability revisions are fresh and compatible. | Agent projection + coordinator receipt/CAS | delayed/reordered poll or config drift | stale over-allocation | fake-clock/reorder tests |
| GPU claim is feasible under explicit provider mode. | GPU resource planner + agent binder | VRAM/model/mode/granularity mismatch | OOM or false isolation | unit/provider contract tests |
| Poll order cannot change global decision. | Pure scheduler snapshot owner | concurrent connections | opportunistic/wrong placement | permutation/multi-agent test |
| One availability revision has one unresolved admission. | Coordinator assignment CAS | concurrent scheduling cycles | duplicate physical request | SQLite barrier test |
| Work cannot select code or leak secrets. | Resident-project resolver + codecs/redactor | malicious payload/offer/error | remote execution escalation/disclosure | security/fuzz boundary tests |
| Request and verified inputs are durable before grant. | Agent journal + relay download | outage during transfer | granted work cannot continue | interruption at every transfer step |
| Final committed refs are coordinator/backend accessible. | Relay finalizer + authority commit validator | agent-local URI/partial upload | downstream cannot materialize | ref-rewrite/digest/commit tests |
| Granted process continues and result replays after coordinator outage. | Authority fence + agent journal/outbox | liveness lease/generation change | lost valid work | real-process restart integration |
| Unknown accepted work is never assigned again. | Coordinator recovery policy + authority fence | offer expiry/agent loss | duplicate execution | multi-agent outage barrier |
| Required store/retention failure fails closed. | Role stores + agent readiness | disk full/schema/corruption | forgotten result or unsafe capacity | fault injection |
| Status derives from source-labelled truth and is redacted. | Joined status builder | stale snapshot/raw provider error | false outcome/secret leak | projection/redaction tests |

## Implementation Slices

1. Add versioned remote session/registration/reconcile/offer/work messages,
   mTLS/scoped principal mapping, direct/HTTP conformance, and negative
   authentication/replay/size/version tests before remote execution is enabled.
2. Add GPU inventory/request/claim planner and binder composition, hard/soft
   specs, global multi-run/multi-agent snapshot scheduling, preference fallback,
   target behavior, pending explanations, and deterministic candidate tests.
3. Implement resident-project capability matching and the assignment-scoped
   artifact relay: pre-grant request/input staging, output retention/upload,
   final accessible refs, authority commit gating, cleanup, and transfer faults.
4. Implement remote agent daemon loop, long-poll/backpressure, grant/start,
   coordinator generation restart, disconnect buffering, reconcile/replay, zero-
   availability restart, and unknown-work behavior with real process barriers.
5. Integrate CLI/Python operations, `machine-A`/`machine-B` deployment examples,
   user-service/TLS guidance, status/redaction, opt-in network/GPU receipts, and
   full multi-run dependency-aware remote E2E validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Remote modules do not make core scheduling/vendor imports heavy. | Import roots without TLS server/GPU SDK/project loading. |
| Unit | required | GPU modes, hard/soft tiers, offer expiry, global order, codecs/auth/redaction. | 12 vs 80 GiB; irrelevant GPU pref; exact target; permutation; invalid role/version. |
| Contract | required | Direct/HTTP application port, resource planner, relay operations, agent journal codecs. | Equivalent traces/errors; stable idempotency; finalized ref never local-only. |
| Integration | required | Assignment races, long polls, mTLS, transfer interruption, agent/coordinator restart, buffered replay. | One admission/start; inputs before grant; valid late commit; no loss redispatch. |
| E2E / opt-in | fake topology required; real network/GPU opt-in | Multi-machine user journey. | `machine-A`/`machine-B`, two runs/DAGs, GPU eligibility/preference, coordinator outage, eventual downstream progress. |

Targeted commands:

    uv run pytest tests/unit/loom/scheduling tests/unit/loom/queue tests/unit/loom/pipeline
    uv run pytest tests/contracts tests/integration/queue tests/integration/pipeline
    uv run pytest tests/e2e/test_queue_cli.py tests/e2e/test_execution_lifecycle.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: certificate identity/body confusion, stale-offer assignment,
  connection-order scheduling, unsafe GPU-sharing inference, project drift,
  grant before inputs, partial upload commit, inaccessible output refs, result
  loss on coordinator outage, replay under a new fence, and auto-redispatch.
- Review focus: direct/HTTP parity, scope matrix, offer/CAS fields, resource-
  relevant preference scoring, agent binding, relay finalization/reference
  ownership, grant/outage trace, bounded retention, and safe diagnostics.
- Stop if: no authenticated path can supply agent inputs without shared paths;
  artifact finalization cannot create coordinator-accessible refs; safe result
  buffering cannot be made durable; provider cannot truthfully bind advertised
  sharing/fraction; arbitrary code shipment becomes necessary; or any accepted
  work must be automatically reassigned.
- Accepted debt and revisit trigger: coordinator relay bottleneck, resident
  project setup, serialized admission handshake, FIFO starvation, no direct
  object backend/peer cache/HA. Revisit on measured throughput/operability harm.

## Executor Handoff

- Read section range: manifest full `Shared Constraints`; planning FR-1, FR-3,
  FR-5 through FR-22, DQ-3 through DQ-10, `Transport, code, and artifacts`, and
  this full phase.
- Safe implementation slices: the five slices above; complete transport/security
  contracts before enabling remote launch and stop before Phase 3 controls.
- Decisions not to revisit: stage readiness remains Phase 1 authority; outbound
  agents; one global snapshot scheduler; explicit GPU modes; hard before soft;
  mTLS/scopes; resident project; inputs before grant; accessible refs before
  commit; outage-stable fence; no automatic unknown-work redispatch.
- Conditions requiring manager action: new public/durable protocol beyond this
  plan, selected vendor dependency, code shipment, peer transfer, GPU semantics
  without provider proof, artifact accessibility failure, HA/auto-recovery, or
  any stop condition.

## Workflow State

- Manager preparation: pending Phase 1 remote merge/worktree/base recording
- Expanded planning: Stage 29 design and plan reviews passed after bounded corrections
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required for remote execution, mTLS, artifact publication,
  global resource/CAS, and outage residual risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
