# Phase 1 Execution Plan: Generic Scheduler And Unified Local Daemon Boundary

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 1
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p1-local-daemon-control-boundary`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop`, recording the exact completed Stage
  25, Stage 27, and Stage 28 contracts used by the phase
- PR target: `develop`
- PR title: `feat(queue): add generic scheduler and durable local daemon`
- Dependencies: completed queue ordering, runtime resources, local GPU/provider
  foundations, explicit extension composition, current managed-local lifecycle,
  queue SQLite, and authority service contracts
- Workflow path: expanded because this phase introduces public/durable placement
  schemas, coordinator/agent SQLite ownership, assignment/start fencing, mTLS
  authorization, and a concurrency-sensitive scheduler-to-CAS boundary
- Blockers: none; preparation must stop and return to planning only if the
  implemented prerequisite contracts materially contradict this accepted plan

## Objective And Context

- Vertical outcome: one command-scoped local run and one persistent co-located
  daemon accept the same versioned whole-run placement request, normalize exact
  CPU/memory quantities, choose through the same concrete scheduler, commit a
  durable assignment, bind resources through the local agent, launch once, and
  expose later authenticated status/cancel operations.
- Earlier dependency: reuse completed queue ordering as the scheduler's job-order
  seam, existing resource validation where its semantics match, and existing
  assignment/provider/process lifecycle rather than recreating them.
- Later work explicitly out of scope: Phase 2 adds authenticated remote agents,
  global candidates, GPU/VRAM claims, machine/model preferences, and outage
  reconciliation. Phase 3 adds live inventory reload and manual recovery.

## Current Source And Harness

- Relevant inspection areas: `src/loom/queue/models.py`, `service.py`,
  `repository.py`, `_sqlite.py`, `_scheduler.py`, `controller.py`, `local.py`,
  `managed_local.py`, `assignments.py`, `status.py`, `config.py`, the completed
  queue-selection/resource/GPU/extension modules found on current develop,
  and the authority application/client patterns.
- Existing tests and seams: queue record/repository/config contracts, SQLite
  integration, scheduler/controller/local adapter/assignment/runtime unit tests,
  managed-local integration/E2E, authority idempotency/generation tests, and
  fakeable process/resource providers.
- Import/dependency constraints: scheduling values and the resource-planner
  protocol stay queue-local and import-light; the pure scheduler imports no
  routes, SQLite, CLI, vendors, agent runtime, or project code. Concrete
  coordinator, agent, HTTP, and daemon composition sit above those values.

## Scope

In scope:

- Schema-versioned whole-run `PlacementRequest` semantics: canonical resource
  payloads, tagged built-in hard/soft specs, hard target, preferred agents,
  fallback policy, and deterministic fingerprint. Legacy integer launch-resource
  records receive an explicit compatible read/migration projection.
- Versioned safe resource request/inventory/claim envelopes plus an immutable,
  explicitly supplied resource-planner registry. Implement the current scalar
  consumers: CPU in exact configured base units and memory in bytes. Claim
  search returns complete/exhausted state plus any sound winner bound. Reject
  unsupported kind/version/unit/granularity before queue mutation.
- One concrete pure scheduler over immutable bounded snapshots. Core hard
  invariants precede tagged built-in rules; default chooses the oldest runnable
  job then the best placement. Search is tri-state and never mutates after an
  older indeterminate job or incomplete selected-job ranking.
- A local-agent inventory/availability projection derived from trusted local
  configuration. Managed pool configuration migrates/composes into one local
  agent without duplicating remote-style capacity in the coordinator.
- Coordinator application service and `SQLiteCoordinatorStateStore` owning
  queue placement requests, assignment/claim/grant transitions, idempotency,
  principal policy, cancellation intent, event acknowledgements, and joined
  status. Assignment CAS revalidates every local snapshot fence.
- Separate `SQLiteAgentJournal` owning receipt, local claim/binding projection,
  proposed acceptance, grant, start fence, process/cleanup observations,
  critical outbox events, and control results. Required writes fail closed.
- Direct authorized client plus mTLS HTTP client/server conformance, local agent
  runtime, one revision-bound work request, persistent co-located daemon, thin
  CLI composition, and migration of managed public facades to this common path.
- Safe local pending/assignment/resource diagnostics, redaction, schema/API
  docs, migration evidence, and representative runnable example.

Out of scope:

- Multiple remote agents, global machine comparison, remote connection/session
  replacement, GPU model/VRAM/fabric/fractional-provider placement, or opt-in
  real-network/GPU evidence; Phase 2 owns these.
- Drain/resume/reload, disconnected cancellation reconciliation, manual
  containment recovery, and different-session replacement; Phase 3 owns these.
- Public replaceable scheduler or custom hard/soft callable protocols, automatic
  plugin discovery, unrestricted constraint language, global solver, batch/gang
  placement, preemption/fairness, global licences, data transfer, HA, or retry.

Assumptions:

- The completed prerequisite implementation supplies the accepted queue-order,
  GPU/provider, and extension seams; their exact private names are not fixed by
  this plan.
- Production local composition may be bounded, but still uses distinct logical
  coordinator and agent SQLite files and the same grant/start ordering as remote.
- Authored project/deployment config is trusted; submit/client payloads and HTTP
  values are untrusted bounded data.

## Fixed Contracts And Private Discretion

- Observable behavior: same placement request and local inventory produce the
  same normalized scheduler decision through command, managed facade, direct
  daemon client, and loopback mTLS client. There is no direct FIFO fast path.
- Public/durable shapes: placement request/resource envelopes are versioned and
  canonical; assignment persists selected safe claims, scheduler policy/version
  evidence, job/attempt and local agent/session/config/availability/work-request
  fences. Full inventory snapshots and rejected candidates remain ephemeral.
- Quantity contract: resource planner owns exact normalized integer arithmetic;
  binary floating-point never owns capacity. CPU fraction/granularity and memory
  unit failures are explicit. Missing requests mean no explicit requirement,
  not invented defaults.
- Rule contract: current hard and soft rules are schema-versioned tagged data
  interpreted by private built-ins. Unknown versions/evaluator errors create no
  assignment. Soft rules never affect feasibility; fallback waiting is separate.
- Search contract: evaluation is complete-feasible, complete-infeasible, or
  exhausted. No younger job can pass an exhausted older job and no partial
  placement ranking can be committed without a sound winner proof.
- Trust/failure boundary: every HTTP peer uses mTLS and a scoped application
  principal; direct calls use the same authorizer. Payload actor/callable-like
  fields have no authority. Required store failure prevents ack, grant, start,
  readiness, or fallback to memory.
- Cross-phase contract: Phase 2 reuses the exact placement, resource, snapshot,
  decision, assignment, grant, journal, and client semantics and only adds
  remote offers/resource kinds/current candidates. Phase 3 preserves old claims
  under their original config fingerprint during drain/reload/recovery.
- Reproducibility/compatibility: stable queue/item/run identities and legacy
  reads remain; delegated adapters bypass managed scheduling; deterministic IDs
  break equal policy ties; scheduler evidence is safe and bounded.
- Private choices: exact module split beneath the documented ownership, SQLite
  table/index/tuning/migration mechanics, HTTP route grouping, daemon supervisor
  example, scheduling loop wake primitive, canonical internal quantity classes,
  and test helper construction.

## Proportionality

- Existing seams reused: queue record/CAS, completed queue order, resource
  validation, authority/idempotency patterns, assignment providers, local
  process lifecycle, status redaction, CLI facades, and fake test harnesses.
- Material additions and current justification: placement schema for nested
  resources/preferences; resource registry for current heterogeneous consumers;
  pure scheduler for one consistent local/remote path; two stores/fences for
  cross-owner restart correctness; mTLS/scopes for code-execution operations.
- Optional hardening and future capability deferred: public scheduler/rule
  substitution, generalized plugin loading, optimal packing, durable candidate
  history, online backup/restore, revocable offline grants, and exactly-once
  authored effects.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Placement request is canonical, version-supported, and immutable after submit. | Placement codec + coordinator submit transaction | legacy/untrusted payload or changed idempotency content | different requirements under one job identity | contract/migration/replay tests |
| Resource quantities and claims use exact resource-owned units. | Resource planner | decimal/unit/granularity boundary | drift or over-allocation | scalar boundary/property-style fixtures |
| Hard rules precede soft rules and soft cannot widen fit. | Concrete scheduler | malformed tag/private evaluator | invalid placement | unit negatives |
| Oldest-runnable/best-placement is never decided from indeterminate search. | Concrete scheduler | search budget or incomplete resource claims | younger/worse placement | tri-state exhaustion tests |
| Same snapshot gives same decision independent of ordering/transport. | Concrete scheduler | mapping/offer order or HTTP projection | topology drift | permutation/client conformance |
| One item/attempt and one availability request produce at most one assignment. | Coordinator assignment CAS | concurrent triggers/lost response | duplicate execution | SQLite barrier/idempotency tests |
| `OFFERED` is not execution authority. | Coordinator grant state + agent runtime | eager agent start | unauthorised/duplicate launch | crash-table tests |
| Local physical claim is acquired/rolled back/released exactly. | Agent provider + journal | stale inventory/partial acquisition | resource overlap/leak | provider integration/failure injection |
| Start fence precedes at most one root launcher invocation. | Agent journal/runtime | crash around launcher | duplicate root process | injected crash table |
| Agent event is durable before send and coordinator commit precedes ack. | Two stores | loss/restart around HTTP response | lost terminal/control truth | outbox replay tests |
| Actor and scope derive from trusted context. | TLS edge + application authorizer | body actor/wrong certificate/scope | unauthorized code/control | direct/HTTP security matrix |
| Local facade has no second scheduler/lifecycle. | Composition root | retained controller claim path | behavior drift | call-graph/trace tests |

## Implementation Slices

1. Inspect and record the completed prerequisite seams; add versioned placement/resource/rule
   records, exact scalar planners, explicit registries, safe codecs/migrations,
   and the concrete tri-state scheduler with focused unit/contract tests.
2. Add coordinator store/application assignment models and transactions,
   scheduling triggers/lock, decision validation, idempotency, cancellation,
   pending explanations, and storage-fault/race tests.
3. Add separate agent journal/outbox and local agent inventory/work/admission/
   grant/start/process/event loop by composing existing providers/adapters.
4. Add the authorized client port, direct client, mTLS HTTP adapter, principal
   policy, daemon activation/role locks, and direct/HTTP conformance/security
   tests.
5. Migrate command/controller/managed-runtime facades and CLI to common
   composition; add end-to-end local persistence/cancel/restart evidence,
   redacted docs/examples, and remove the managed direct scheduling branch.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional cheap scheduler/client/resource imports. | Public imports succeed without routes/SQLite/vendor/plugin discovery. |
| Unit | required | Schemas, exact quantities, rule order, tri-state scheduler, state machines, auth, redaction. | Fraction/unit/version failures; deterministic oldest-runnable; no mutation on exhaustion; safe reasons. |
| Contract | required | Placement/resource codecs, resource planner, coordinator client, direct/HTTP parity, legacy reads. | Stable round trip/version failure/idempotency and equivalent normalized traces. |
| Integration | required | SQLite assignment races/faults, provider rollback, outbox replay, cancel/start, persistent clients, facade migration. | One assignment/start; no failed-write ack; exact release; no second path. |
| E2E / opt-in | required local; real remote/GPU deferred | Command and co-located daemon lifetime. | Submit in one invocation, later status/cancel, restart with durable state, redacted evidence. |

Targeted commands:

    uv run pytest tests/unit/loom/queue tests/contracts/test_queue_records_contract.py tests/contracts/test_queue_python_api_contract.py
    uv run pytest tests/integration/queue tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: over-broad public API, lossy legacy migration, float accounting,
  incomplete search mutation, duplicate scheduler path, cross-store false
  atomicity, start-before-grant, store failure fallback, and HTTP/direct auth
  divergence.
- Review focus: one concrete scheduler; exact resource ownership; tri-state
  completeness; assignment CAS fields; agent admission rollback; grant/start/
  outbox ordering; separate stores; no route/facade policy; redaction.
- Stop if: completed prerequisite contracts materially differ; compatibility needs
  silent reinterpretation; one local job requires multi-agent allocation; a
  resource cannot expose safe deterministic claims; correctness requires a
  cross-store transaction; or mTLS/authorization cannot be proven before code
  execution.
- Accepted debt and revisit trigger: bounded oldest-runnable starvation,
  serialized agent handshake, no optimal packing/custom rule protocol/HA. Revisit
  only with measured harm or an accepted concrete consumer.

## Executor Handoff

- Read section range: manifest shared constraints; planning FR-1 through FR-18,
  FR-20, FR-23, FR-27, FR-28; DQ-1 through DQ-12, DQ-14, DQ-15; this full phase.
- Safe implementation slices: the five slices above in order; stop after phase
  tests and do not implement Phase 2 remote/global GPU behavior.
- Decisions not to revisit: one concrete scheduler, tagged built-in rules,
  exact resource units, oldest-runnable then best placement, tri-state no-
  mutation exhaustion, separate role stores, grant/start/outbox ordering, mTLS/
  shared authorizer, one local managed path.
- Conditions requiring manager action: source-contract mismatch, durable schema
  incompatibility, public API expansion, another scheduling algorithm, custom
  hard/soft callable requirement, cross-store transaction, or stop condition.

## Workflow State

- Manager preparation: pending current worktree/base and prerequisite-contract recording
- Expanded planning: generic-scheduler removal-first review passed after bounded
  tri-state/protocol correction
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified product blocker is returned
- Pre-submit gate: pending
- Independent review: required because Phase 1 combines new durable schema,
  assignment/start concurrency, and remote code-execution security boundaries
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
