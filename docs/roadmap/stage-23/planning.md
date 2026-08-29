# Roadmap v23 Planning: Managed Local Concurrency And Resource Assignment

Status: confirmed; implementation-plan quality gate passed
Roadmap stage: v23
Evidence: `main` at `68f43f12f7d99b2845a64265b1f5d82300273280`;
relevant paths unchanged on `origin/develop` at
`a6bd1ef54523ac394b6a875c7486f9d8d7f68b95`; unrelated dirt preserved
Planning route: expanded because the change crosses public dispatch results,
coordination failure semantics, queue persistence, and managed-process safety
Current gate: planning workflow complete; Phase 1 not started
Blockers: none

V23 builds on the completed FIFO queue without reopening historical records. It
lets one managed-local controller run several items against concrete static
resources, without implementing v26's generic scheduler.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Current queue, coordination, config, status, tests, completed v11, and roadmap v26 were inspected at the stated baseline. | None. | Preserve the existing end-to-end path and import direction. |
| Functionality | A selected managed pool reconciles all active items, fills to a positive configured limit, defers ordinary pre-start capacity shortage, renews live leases, and exposes redacted assignment/log evidence. Existing behavior defaults to one active item. | None. | Hold the behavior boundary. |
| Design safety | Removal-first review removed recovery/provider machinery without a consumer, per-renewal queue writes, a resource-instance schema, configurable log paths, and premature scheduler reuse claims. | None. | Keep private names and representations open. |
| Validation and phases | Three accepted vertical phases cover safe cycling, managed-local assignment/lifecycle, and operator proof. | None. | Review the manifest and linked phase plans. |
| Approval | User confirmed planning and the corrected plan-quality gate passed on 2026-08-17. | None. | Select Phase 1 only through the implementation workflow. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `docs/roadmap.md`, completed v11 artifacts, and v26 | V11 owns a narrow whole-run FIFO queue; v26 must decide generic scheduling and explicitly defers new scheduler policy until its design stage. | Placement and non-goals. | FR-1, FR-12 |
| Queue feature docs and `src/loom/queue/` | `run_once()` changes at most one item; dispatch is complete-or-active; the local adapter holds process and admission state in memory; status serializes broad handle evidence. | Compatibility, lifecycle, and redaction boundaries. | FR-1 through FR-10 |
| Queue repository and SQLite implementation | FIFO columns exist, but claim is a read followed by an unguarded update and later mutations check too little identity. The serialized item can hold safe assignment evidence without new tables. | Atomic claim, CAS, and schema choice. | FR-4, FR-5, FR-10 |
| Resource admission and coordination stores | Scalar acquisition compensates partial success, but retryability is partly inferred from exception text; leases can renew and are authority-owned. | Typed outcomes, static slots, and renewal. | FR-3, FR-6 through FR-9 |
| Existing tests | Serial lifecycle, process groups, admission release, delegated handoff, and SQLite persistence are covered; concurrent claim, refill, assignment, renewal, and redacted summaries are not. | Proportional validation. | all |

- User-visible outcome: twelve ordinary commands can be queued to one managed
  pool backed by three configured static slots; one controller runs at most
  three, refills on later cycles, captures distinct logs, and never assigns one
  slot to two live items while authority fencing is valid.
- Existing path: queue config -> `QueueService` -> SQLite FIFO claim -> injected
  dispatch adapter -> local process group -> reconciliation/status. No parallel
  scheduler or resource database is introduced.
- Included: pool-scoped reconcile/fill cycles, bounded work per cycle, guarded
  deferral and mutation, typed capacity/authority outcomes, no-op and static-slot
  assignment, configured environment-list bindings, live-owner renewal,
  deterministic per-attempt logs, config/preflight, and redacted pool status.
- Deferred: discovery, vendor APIs, topology/utilization placement, priorities,
  fairness, preemption, retries, multi-host inventory, stage scheduling,
  worker supervision, process reattachment, and plugin discovery.
- Affected contracts: dispatch and cycle results, provider injection records,
  queue config, repository operations, safe handle evidence, status JSON, and
  coordination/admission failure kinds.

## Minimum Useful Change

- A selected managed-local pool gains a cycle operation that first reconciles
  every active item and then fills available capacity. `run_once()` remains a
  one-step compatibility operation and legacy config remains effective at one.
- Reuse `QueueController`, `LocalQueueDispatchAdapter`, scalar admission,
  authority named leases, `DispatchHandle.evidence`, and the SQLite queue. A
  second scheduler, durable slot inventory, and vendor adapter are unnecessary.
- A non-terminal pre-start refusal is required because today's active/complete
  result cannot distinguish normal capacity pressure from failure. Static slots
  need one narrow injectable provider boundary because logical integer resources
  cannot identify exclusive concrete instances.
- `max_active_items` is a single-controller policy, not a distributed quota.
  Multiple controllers remain safe from duplicate claims and slot double-use,
  but can exceed that item count when items use no constrained authority
  resource. Exact cross-controller item quotas are explicitly deferred.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-1 | One pool cycle reconciles every active item, records per-item outcomes, then claims/dispatches until the active limit, FIFO capacity block, empty queue, bounded cycle budget, or fail-closed error. Reconciliation continues after an item-local error, but degraded authority/ownership evidence prevents new starts. | No cross-pool fairness; starts may be sequential. | Mixed reconciliation, fill/refill, budget, and compatibility tests. | locked |
| FR-2 | Concurrency is opt-in and positive; schema-v1 config and `run_once()` preserve current one-active/one-step behavior. | The new cycle/managed loop is explicit. | Config and public controller contracts. | locked |
| FR-3 | Dispatch distinguishes started, synchronously completed, and deferred-before-start. Only typed capacity exhaustion defers; invalid/unsupported work fails, while authority uncertainty or fencing loss degrades the cycle. | No message parsing and no automatic retry. | Outcome and backend-parity contracts. | locked |
| FR-4 | Deferral restores the same item to `QUEUED` without changing enqueue order or dispatch attempt, clears the claim, audits a non-secret reason code, and stops claims from that FIFO for the cycle. The adapter must have started no process and released partial resources before deferral. | No requeue/resubmit semantics change. | Immediate-reclaim-loop and rollback tests. | locked |
| FR-5 | SQLite claims are atomic across connections and every reclaim gets a non-reusable identity. Deferral, handle commit, completion, and cancellation verify status plus claim, owner, attempt, adapter, and handle identity in one transaction; stale writers conflict. | No distributed repository backend. | Barrier claim, same-owner reclaim, and stale mutation tests. | locked |
| FR-6 | Core supplies no-op assignment and an ordered static-slot provider. Static slots acquire distinct authority keys provisioned at limit one, select deterministically, support multi-slot requests, and compensate partial acquisition. | No inventory table, health discovery, or provider registry. | Ordering, exclusivity, contention, and rollback tests. | locked |
| FR-7 | The injectable provider receives only consumer/pool identity, logical amounts, and admitted lease references, and returns a typed decision, live cleanup token, safe evidence, and environment-list bindings. It owns assignment acquire/renew/release; the local adapter owns ordering, process lifecycle, and exactly-once orchestration. | No full `QueueItem`, callback bag, public recovery hook, or generic placement policy. | Protocol fake and lifecycle tests. | locked |
| FR-8 | Local launch validates drift/command, acquires scalar admission then assignment, applies deterministic conflict-checked bindings, starts the process, and commits safe handle evidence. Any failure unwinds in reverse order. Failure to persist a started handle terminates and confirms the process before releasing resources. | Existing CPU-only behavior uses no-op assignment. | Injected failure matrix including handle-commit failure. | locked |
| FR-9 | A live managed owner renews scalar and assignment leases before a tested safety deadline. Definitive ownership loss or an unresolved outage at the deadline stops new fill and terminates the process group; resources are released only after exit is observed. | No guarantee after controller death, unkillable process, or missed scheduling deadline; no reattachment. | Fake-clock renew/loss/kill tests. | locked with accepted risk |
| FR-10 | Each attempt writes distinct deterministic stdout/stderr files under queue state. Persisted/status evidence is allowlisted: safe provider/slot labels, owner/session, PID/PGID, resource/lease IDs and expiry, and queue-relative log paths; it excludes fencing tokens, command/cwd, environment names and values, and provider-private payloads. | No configurable external paths or log-follow command. Existing broad evidence remains readable but is never emitted raw by the new summary. | Collision, legacy-record, redaction, and JSON/text parity tests. | locked |
| FR-11 | Preflight validates new config shape, positive limits, unique/non-colliding slot keys, binding conflicts within static inventory, and required authority capabilities/limits. Item-specific requests remain validated at enqueue/provider boundaries. | Queue never provisions authority limits; avoid duplicate future-work validation. | Focused negative config and runtime boundary tests. | locked |
| FR-12 | Delegated SLURM, fake/custom/synchronous adapters, CPU-only managed pools, queue identity, and scheduler-neutral records remain compatible. This stage adds no general scheduling vocabulary on v26's behalf. | No SLURM mapping change. | Existing suites and import/public-surface tests. | locked |

## Functionality And Design Agreement

| ID | Related IDs | Decision and rationale | Tradeoff | State |
| --- | --- | --- | --- | --- |
| A-1 | FR-1 through FR-5 | Add one batch cycle and one deferred result while retaining legacy one-step behavior. Repository owns atomic state transitions; controller alone decides FIFO/cycle policy. | Two controller operation levels remain. | repo-resolved |
| A-2 | FR-3, FR-6 through FR-9 | Coordination implementations expose stable `capacity`, `invalid_or_unsupported`, `unavailable`, `ownership_lost`, and `internal` kinds; admission/provider decisions preserve them. Classification occurs once at the coordination boundary, never from message text. | Compatible typed errors/results are added across backends. | repo-resolved |
| A-3 | FR-6 through FR-8 | Loom owns generic lifecycle safety and ships static slots; downstreams may inject a structural provider for discovery or placement. Keep one coupled lifecycle protocol, not independent callbacks or an inheritance tree. | A small public injection contract is necessary, but its implementations stay external. | locked |
| A-4 | FR-6, FR-7, FR-10 | Keep logical requests portable and assignment local to execution. Persist one schema-tagged, allowlisted assignment subdocument in existing handle evidence rather than a public resource-instance record/table. | Provider-private recovery data is not durable. | repo-resolved |
| A-5 | FR-2, FR-11, FR-12 | Accept schema-v1 queue config unchanged; new declarative settings use schema v2 and normalize legacy defaults. Constructor injection stays first-class. Do not add a separate plugin registry, configurable log schema, or independently versioned status envelope. | Writers using new settings must opt into v2. | repo-resolved |
| A-6 | FR-9 | Guarantee timely renewal and fail-closed action only while the controller/session is alive and cycling. A generated session distinguishes a restarted adapter from its previous in-memory work; foreign sessions count as active but require existing explicit recovery. | Controller crash can leave a process alive past lease expiry. | accepted limitation |
| A-7 | FR-12 | Keep assignment an adapter mechanism, not a scheduler decision. V26 may reuse concepts only after reviewing queue, stage, authority, and executor contracts together. | No promised future scheduler reuse. | repo-resolved |

## Minimum Design

- `loom.queue.controller` owns reconcile/fill sequencing, active counting, cycle
  budget, and compatibility operations. The repository owns transitions and
  filtering, not retryability. `loom.queue.local` owns scalar/assignment/process/
  log composition. The provider owns only its concrete leases and bindings.
- Flow: list active pool items -> inspect only the current adapter session ->
  renew before due -> record terminal outcomes -> count all remaining active
  items, including foreign sessions -> atomically claim FIFO -> dispatch ->
  commit started handle, complete synchronously, or guarded-defer -> continue or
  stop according to the typed result and budgets.
- Public contracts are limited to a serializable cycle result, a deferred
  dispatch discriminator/reason, and the provider injection protocol plus its
  immutable request and discriminated result. A success carries a provider-owned
  opaque live token and a separate plain-data safe projection. Exact names,
  helper layout, cleanup state machine, query grouping, and log filename
  punctuation remain private.
- Live provider tokens remain in adapter memory. Durable handle evidence carries
  only the schema-tagged safe projection needed by recovery/status; renewal does
  not rewrite the queue row each cycle. Status labels persisted acquisition
  evidence separately from optional live observation.
- Static authored inventory describes eligible slot IDs, safe display labels,
  authority keys, and binding values. Authority limit-one leases alone decide
  exclusivity. Scalar admission occurs first; partial slot selection and scalar
  admission are released before a capacity deferral. Slot authority keys cannot
  equal logical resource keys.
- The managed loop schedules its next cycle before the earliest lease safety
  deadline. Manual cycle callers receive the next required maintenance time and
  are responsible for invoking it; missing it is unsupported, not silently safe.
- No queue DDL is currently justified. Claim starts a SQLite write transaction
  before FIFO selection; guarded updates may compare the persisted prior item
  and affected row count. DB schema stays v1 unless implementation evidence
  proves a column/index is necessary. Config alone advances to v2.
- Queue may depend on public pipeline resource/admission and coordination
  contracts. Coordination and pipeline planning never import queue; core imports
  no accelerator, container, scheduler, or downstream provider package. New root
  exports must be intentional and import-light.

## Complexity Delta And Removal-First Review

| Item | Current necessity or finding | Decision |
| --- | --- | --- |
| Cycle result and deferred outcome | Required by a current multi-item controller and safe capacity refusal. | keep, without freezing extra fields beyond outcomes/counts/deadline |
| Guarded queue mutations | Required by reachable multi-connection races. | keep |
| Coupled assignment provider | Required for one current static implementation and downstream injection. | keep narrow |
| Typed coordination failures | Required to distinguish safe deferral from uncertainty. | keep one authoritative classification |
| Durable assignment class/table | Existing handle evidence supports the safe projection; live provider data has no restart consumer. | remove |
| Provider recovery hook and plugin registry | No process reattachment or second discovered provider exists. | remove/defer |
| Per-renewal evidence writes | Status can distinguish persisted acquisition from live observation. | remove |
| Distributed item semaphore | Concrete authority leases enforce resource safety, and the brief selects one controller. | defer; disclose item-limit semantics |
| Configurable log paths and future binding kinds | Deterministic queue-local files and one environment-list binding satisfy current use. | remove/defer |
| Watchdog/supervisor | Required for a crash-time process-death guarantee, which this stage does not claim. | defer with trigger |

## Expanded Design Review

| Finding | Evidence and consequence | Resolution | Status |
| --- | --- | --- | --- |
| Active-limit wording overstated distributed behavior. | Two controllers can read the same count and each start work even when claims are atomic. | Limit is explicitly single-controller policy; slot/scalar leases are the distributed safety boundary. | resolved |
| Renewal wording implied crash safety and unsafe release. | In-memory process ownership cannot act after controller death; releasing before confirmed exit permits overlap. | Scope guarantee to live timely owner, confirm exit before release, and record crash/unkillable cases as recovery risks. | resolved |
| Durable/provider design exceeded current consumers. | No reattachment path consumes provider-private durable state or recovery callbacks. | Keep live tokens private and one safe evidence subdocument; remove recovery hook, table, and per-renewal writes. | resolved |
| Config/status versioning was inconsistent with source. | Current config accepts only schema 1 and status has no independent envelope version. | Accept v1, introduce v2 only for new config, and compatibly extend the existing redacted read model. | resolved |
| Existing status can expose broad handle evidence. | Local handles currently include command/cwd and full admission serialization. | New summaries use an allowlist and new writes omit fencing/binding/command data; legacy rows need no migration. | resolved |

## Examples And Validation

| Invariant | Owner and minimal coverage | Status |
| --- | --- | --- |
| Twelve commands over three static slots peak at three under one controller; completing one allows one replacement; assignments remain unique. | Controller + provider + real SQLite coordination integration. | planned |
| Racing SQLite connections cannot claim one item twice; stale claim/handle writers cannot defer, complete, or cancel it. | Repository barrier/CAS tests. | planned |
| Capacity after partial scalar/slot acquisition unwinds fully and preserves FIFO attempt/order. | Provider/local adapter/repository combined test. | planned |
| Process-start or handle-commit failure leaves no unrecorded process or reusable lease before confirmed exit. | Local adapter/controller injected-failure test. | planned |
| Renewal outage retries only before the safety deadline; loss/deadline stops fill and kills; foreign session is counted but not inspected. | Fake clock/process and coordination backend contract tests. | planned |
| Binding conflicts fail before process start; logs are distinct; text/JSON show identical allowlisted facts and no token, command, cwd, or environment data, including legacy records. | Contract plus dependency-free subprocess e2e. | planned |
| Two controllers may exceed `max_active_items` for unconstrained no-op work but never duplicate a claim or hold the same static slot. | Explicit semantics integration test. | planned |

Causal combined coverage is required only for claim+defer+FIFO stop,
scalar+slot+start/commit compensation, and reconcile+renew+terminal
release+refill. Backend error-category parity is a contract matrix; unrelated
config and process cases stay focused rather than Cartesian.

## Phase Shaping

| Phase | Vertical outcome | Scope and acceptance | Status |
| --- | --- | --- | --- |
| 1. Safe pool cycles | Reconcile/fill one pool with bounded work, typed deferral, non-reusable atomic claims, guarded transitions, scalar lease renewal, safe local termination/handle-commit compensation, session ownership, and legacy one-step compatibility. | accepted |
| 2. Managed-local assignments | No-op/static providers, config v2/preflight, bindings, deterministic logs, and assignment renewal extend Phase 1's local lifecycle without changing its process/release guarantees. Real SQLite coordination and fake-clock/process tests prove exclusivity. | accepted |
| 3. Operator proof | Filtered pool reads and redacted text/JSON summaries expose counts, safe assignment/process facts, and log paths; docs and twelve-over-three e2e prove the supported single-controller path. Existing suites, `make validate-pr`, and `make test-summary` remain gates. | accepted |

Three phases are justified because controller/scalar-process safety, concrete
assignment, and operator compatibility are independently reviewable. Phase 1
lands renewal and post-start compensation before concurrency becomes usable.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1 through FR-12 and A-1 through A-7 define supported and unsupported behavior. | pass |
| Minimum design justified | Existing queue, admission, coordination, handle evidence, and status paths are reused. | pass |
| Complexity proportionate | Speculative schema, recovery hook, registry, renewal writes, log config, and scheduler abstractions were removed. | pass |
| Contracts and private discretion clear | Public/durable guarantees are separated from names and local wiring. | pass |
| Invariant ownership and validation proportionate | Each safety boundary has one owner and only causal interactions combine. | pass |
| Phases vertical and reviewable | Each phase delivers a testable end-to-end increment with explicit exclusions. | pass |
| No unresolved design blocker | Expanded findings are resolved and the user confirmed the artifact. | pass |

Gate result: confirmed by the user on 2026-08-17; the corrected implementation
manifest and phase plans passed their quality gate. No phase has started.

Accepted risks and revisit triggers:

- Revisit an exact distributed item quota when multiple active controllers must
  share a pool independently of constrained authority resources.
- Revisit watchdog/process reattachment when unattended restart must guarantee
  process death or continued lease ownership.
- Revisit durable inventory/discovery only after static config cannot represent
  a current environment or two downstream providers duplicate bootstrap code.
- Revisit queue DDL when measured query/CAS behavior requires an index, revision,
  or first-class safe evidence column.
- Revisit generic scheduling only in v26's cross-contract design review.

## Decisions And Deferrals

| Item | Decision or deferral | Revisit trigger |
| --- | --- | --- |
| Core/downstream ownership | Loom owns lifecycle safety and static slots; downstream owns domain semantics, discovery, health, and site placement. | Narrow protocol cannot express a demonstrated provider. |
| Persistence | Reuse QueueItem/SQLite schema v1 and schema-tagged safe handle evidence; config advances compatibly to v2. | Proven query, migration, or recovery consumer. |
| Multi-controller behavior | Atomic claims and authority leases are hard safety; `max_active_items` is not a distributed semaphore. | Exact cross-controller quota requirement. |
| Crash behavior | Live timely owners renew and fail closed; controller death is recovery-needed, not fail-stop. | Unattended crash guarantee becomes accepted scope. |
| Scheduler compatibility | Preserve scheduler-neutral queue/resource records without defining v26 policy. | Reviewed v26 scheduling design. |
| Implementation authorization | Plan quality passed; Phase 1 may be selected only through its phase workflow. | A phase is selected. |
