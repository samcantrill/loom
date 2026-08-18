# Phase 2 Execution Plan: Managed Local Assignments

## Metadata

- Status: merged
- Roadmap stage and phase: v23 Phase 2
- Manifest: `docs/roadmap/stage-23/implementation-plan.md`
- Branch: `agent/stage-23-p2-managed-local-assignments`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-23-p2-managed-local-assignments`
- Base revision: `e47ed7796d61169d54846b2a2f60c2970b88116e`
- Planning evidence revision: `0baa20e`
- PR target: `develop`
- PR title: `Managed Local Concurrency - Phase 2: Static Assignment Lifecycle`
- Dependencies: Phase 1 remotely merged and its disposition, guarded mutation,
  typed failure, and cycle contracts unchanged
- Workflow path: expanded because this phase adds a public provider protocol,
  config-v2 records, exclusive leases, renewal deadlines, and process/resource
  compensation
- Blockers: none; the maintainer authorized one bounded correction beyond the
  normal 3/3 limit and the mixed per-slot release finding is resolved

## Objective And Context

- Vertical outcome: the built-in managed-local adapter can run several items
  concurrently, give each a deterministic exclusive static slot, apply a safe
  environment binding, capture distinct logs, renew all live leases, and release
  owned resources only after the process is terminal.
- Earlier dependency: Phase 1 supplies typed deferral, guarded persistence,
  session ownership, scalar renewal/deadlines, terminal-before-release, and
  post-start handle-commit compensation.
- Later work explicitly out of scope: pool summary/CLI rendering and the final
  twelve-over-three operator proof, plus dynamic discovery, vendor health,
  topology, multi-host placement, provider loading, or process reattachment.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/local.py`: `LocalQueueDispatchAdapter`, process runner
    protocols, `_ActiveLocalDispatch`, launch normalization, scalar admission,
    inspect/cancel, and current broad evidence.
  - `src/loom/queue/config.py` and `preflight.py`: normalized queue config,
    authority capability/limit checks, and no current adapter-assignment model.
  - `src/loom/queue/controller.py`: Phase 1 disposition/cycle contract and the
    existing cancellable/inspectable adapter seams used for compensation.
  - `src/loom/pipeline/execution/resource_admission.py` and
    `src/loom/pipeline/stores/coordination.py`: lease records, renewal, release,
    and Phase 1 failure kinds.
  - `src/loom/queue/models.py`: unchanged `DispatchHandle.evidence` durability
    boundary.
- Existing tests and seams: local adapter fake processes, process-group
  integration, managed-resource contract tests, queue preflight, coordination
  backend contracts, config contracts, and existing local-controller tests.
- Import, dependency, or harness constraints: provider contracts live inside
  `loom.queue`; no package-wide protocol or vendor module. Static assignment
  uses only `WorkspaceCoordinationStore`; queue never calls resource-limit
  mutation. Subprocess logs use ordinary files and argument vectors.

## Scope

In scope:

- Queue-local immutable assignment request/decision/binding/evidence records and
  one structural `ResourceAssignmentProvider` lifecycle protocol.
- No-op and ordered static-slot providers. The static provider attempts slots in
  authored order, skips only typed capacity conflicts, selects distinct slots
  for multi-slot requests, and compensates every partial acquisition.
- Config schema v2 under `adapters.local.assignments.<pool>.<resource>` with
  `provider: static-slots`, ordered `slots` (`id`, `coordination_key`, `value`,
  optional safe `label`), and one `environment-list` binding (`name`,
  non-empty `separator`). Constructor injection remains first class.
- Preflight for known managed pools/resources, positive/controller limits,
  unique IDs and authority keys, logical/slot-key collision, inventory versus
  scalar pool capacity, environment-safe names/values/separator, authority
  resource-lease/renewal capability, logical limits matching pool config, and
  slot-key limits exactly one. Preflight reads but never provisions limits.
- Enqueue/provider-boundary rejection when one item requests more configured
  slots than can ever fit.
- Local launch order: drift check, trusted argv/env normalization, scalar
  admission, concrete assignment, deterministic conflict-checked binding,
  per-attempt log preparation, process-group start, then safe handle evidence.
- Integration of assignments into Phase 1's adapter-session, multi-process,
  handle-commit compensation, terminal-before-release, and release-once state.
- Assignment renewal alongside scalar renewal using Phase 1's 50% due point,
  80% safety deadline, typed transient retry, immediate ownership-loss action,
  and earliest-maintenance aggregation.
- Deterministic stdout/stderr files beneath queue-owned state, with distinct
  paths per item and attempt and queue-relative paths in safe evidence.

Out of scope:

- Provider discovery/registry, recovery hook, durable live token, new queue or
  authority schema, automatic inventory, vendor APIs, arbitrary argv/mount/
  device rewriting, external log paths, shell strings, per-renewal queue writes,
  watchdog/daemon, or crash-time process guarantees.

Assumptions:

- Static assignment rules handle only their configured logical keys; other
  logical resources remain scalar-admission-only. No-op assignment preserves
  all current CPU-only/local behavior.
- Authored pool capacity for a static-assigned key equals its slot inventory;
  every slot authority key is separately provisioned with limit one.
- The managed loop or manual caller invokes the next cycle no later than the
  returned maintenance time. Missing that deadline is unsupported and is not
  described as safe renewal.

## Fixed Contracts And Private Discretion

- Observable behavior: slot order and joined binding values are deterministic;
  identical pre-existing environment values are accepted and different values
  fail before process start. Capacity exhaustion defers; invalid config/request
  fails; uncertain authority truth degrades the cycle.
- Public or durable shapes: `loom.queue.assignments` and the `loom.queue` facade
  export `ResourceAssignmentProvider`, `ResourceAssignmentRequest`,
  `ResourceAssignment`, `ResourceAssignmentDecision`,
  `ResourceAssignmentDisposition`, `LaunchEnvironmentBindings`,
  `NoOpResourceAssignmentProvider`, and `StaticSlotAssignmentProvider`.
  Disposition values are `assigned`, `deferred`, and `failed`. The structural
  protocol fixes `provider_name`, `acquire(request) -> decision`,
  `renew(assignment) -> assignment`, and
  `release(assignment, *, reason: LifecycleReason) -> None`.
  `ResourceAssignmentRequest` fixes `consumer_id`, `pool_name`, `owner_id`,
  `session_id`, logical `resources`, admitted lease IDs, and lease TTL.
  `LaunchEnvironmentBindings` contains only an environment mapping.
  `ResourceAssignment` fixes `provider_name`, opaque `live_token`, assignment
  leases, bindings, `safe_evidence`, and `next_maintenance_at`.
  `ResourceAssignmentDecision` fixes disposition, optional assignment,
  `reason_code`, and plain-data reason context: assigned requires an assignment;
  deferred/failed forbid one. The public provider boundary is only these four
  operations and their records: it does not imply registration, discovery,
  recovery, callbacks, or a separately durable provider state. Any plain-data
  serialization of a decision excludes the live token.
  Successful renewal returns the full replacement assignment; typed renewal
  failure leaves the prior assignment owned until Phase 1's deadline/termination
  path resolves it. The adapter atomically replaces its private current
  assignment only after successful renewal. Release consumes that current
  assignment exactly once; the protocol does not prescribe provider-internal
  token or lease bookkeeping.
  Phase 2 extends Phase 1's schema-tagged `managed_local` handle evidence with
  only two nested projections. `assignment` contains `provider_name`, `slots`,
  and `next_maintenance_at`; each `slots` entry contains `resource_name`,
  `slot_id`, `lease_id`, `expires_at`, and optional `label`. `logs` contains
  `stdout_path` and `stderr_path`, both queue-relative. Tests assert those
  complete required/optional key sets at every nested level. The projection
  excludes coordination keys, fencing tokens, command/cwd, binding names and
  values, absolute paths, and all provider-private payloads. Renewal does not
  add per-renewal durable evidence.
- Authored schema boundary: schema v2 accepts exactly the recorded
  `static-slots` provider record and `environment-list` binding under
  `adapters.local.assignments.<pool>.<resource>`; schema v1 has no assignment
  record and continues to normalize to the no-op provider. Parsing and
  preflight may use private normalized records. Preflight reads configured
  authority capabilities and limits but performs no DDL, limit mutation,
  inventory discovery, or provider loading.
- Trust and failure boundaries: authored argv/env and assignment config are
  trusted, but are validated before crossing `subprocess`. Every failure after
  scalar acquisition unwinds the resources actually acquired in reverse order.
  Assignment deferral/failure, binding rejection, log preparation failure, and
  process-start failure therefore release assignment if present and then scalar
  admission without publishing an active handle. If handle persistence fails
  after start, the controller uses the adapter's existing cancellation boundary
  with the just-created handle, confirms process exit, and only then releases
  assignment and scalar resources.
- Coupled renewal boundary: scalar and assignment leases retain their own due
  times and safety deadlines, while the cycle exposes their earliest required
  maintenance time. A typed transient failure keeps the current owned value and
  requests a retry no later than its existing safety deadline. Definitive
  ownership loss, or reaching either deadline without a successful renewal,
  fails the whole local dispatch closed: request process-group termination,
  confirm terminal state, then release the other still-owned assignment/scalar
  resources exactly once. A scalar success cannot mask assignment loss, nor an
  assignment success scalar loss.
- Cross-phase contracts: Phase 3 reads only the safe evidence projection and
  may label optional same-session inspection separately. It must not depend on
  live tokens or binding values.
- Reproducibility and compatibility: `LaunchContract.resources` remains a
  logical integer mapping and queue records gain no slot/vendor field.
  Schema-v1 config normalizes to no-op assignment/one active item. Existing
  fake/custom/SLURM adapters and local call sites without assignment continue.
- Private choices the executor may simplify: normalized config types, active
  state representation, cleanup/evidence helpers, log filename punctuation,
  opaque token type, provider helper layout, and factory wiring. Exported
  names/methods/discriminators, authored config spelling, the persisted evidence
  allowlist, and observable renewal/compensation semantics are fixed.

## Proportionality

- Existing seam reused: constructor-injected local adapter dependencies,
  `DispatchHandle.evidence`, named resource leases, scalar admission,
  process-group runner, queue preflight, and Phase 1 deferral/cycle result.
- Material additions and current justification: one provider protocol separates
  generic lifecycle safety from placement; one static implementation satisfies
  the current consumer; assignment renewal extends Phase 1's necessary scalar
  renewal; deterministic logs distinguish concurrent attempts.
- Optional hardening and future capability deferred: ABC hierarchy, independent
  callbacks, atomic multi-resource inventory query, plugin discovery, public
  recovery API, dynamic slot health, topology, external logs, and supervisor.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Two valid live assignments never hold the same static slot lease. | Static provider plus authority | Concurrent providers race for one authored slot. | Concrete resource overlap. | Real SQLite coordination with multiple adapter instances. |
| Partial scalar or slot acquisition never leaks usable capacity. | Admission/provider; local adapter orchestrates | Assignment defers/fails after scalar admission, a later slot conflicts, or binding/log/start fails after assignment. | Starvation or false capacity. | One focused test per distinct owned-state transition; no Cartesian fault matrix. |
| A process is terminal before its scalar/slot leases are released. | Local adapter | Cancellation, renewal loss, or commit failure releases immediately after signal. | Replacement overlaps a still-running process. | Fake process wait/escalation and commit-failure tests. |
| Live scalar and assignment leases renew before their respective safety deadlines or the whole dispatch fails closed. | Local adapter and controller maintenance schedule | One lease class renews while the other is transient, lost, or overdue during a long process. | Process silently runs with only partial authority. | Fake monotonic clock proves earliest maintenance, one-class transient retry, and either-class loss/deadline termination. |
| Launch binding cannot silently override authored environment. | Binding application | Snapshot provides a different value for the configured name. | Work runs on unintended resource. | Same-value allow and different-value reject tests. |
| Status-safe evidence contains no launch secret or fencing authority. | Local adapter evidence builder | Broad admission serialization or command/env is persisted. | Credential/command disclosure. | Exact-key allowlist and negative serialization assertions. |

## Implementation Slices

1. Add assignment contracts plus no-op/static providers and focused deterministic
   selection, contention, partial compensation, and fake-provider tests.
2. Extend schema-v2 config normalization and preflight/authority checks; retain
   schema-v1 defaults and Python constructor injection.
3. Extend Phase 1's local active state with assignment and logs; add deterministic
   binding, queue-owned log preparation, and safe evidence.
4. Compose assignment acquire/renew/release into Phase 1's compensation,
   terminal-before-release, and earliest-maintenance paths. Keep acquisition
   synchronous with the established dispatch step; do not add background
   renewal, callbacks, or durable recovery state.
5. Prove multiple local handles, unique slots, distinct logs, exact cleanup,
   foreign-session non-inspection, and compatibility across unit, contract, and
   real-SQLite integration tests.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional assignment/local exports and cheap queue import. | Protocol/records/built-ins import without optional/vendor dependencies. |
| Unit | required | Selection, binding, config/preflight, renewal, cleanup, logs, and multi-handle state. | Deterministic multi-slot order; rollback at each distinct owned-state transition; earliest deadline; either-class loss fails closed; each release once. |
| Contract | required | Provider fakeability, authored config v1/v2, failure kinds, evidence allowlist, and no authority mutation. | Public decisions obey their discriminator invariants; v1 normalizes to no-op; v2 accepts the fixed records; preflight only reads; complete evidence key sets match and forbidden keys are absent. |
| Integration | required | Static slots over real SQLite coordination and local controller cycles. | More items than slots; unique active slots; capacity deferred without attempt/FIFO change; success/failure/cancel refill only after terminal release; foreign session preserved. |
| E2E / opt-in | default subprocess proof deferred to Phase 3; real accelerator profile remains opt-in | Phase 2 owns lifecycle mechanics, while Phase 3 owns the documented operator journey. | No real accelerator, vendor command, or external service in default gates. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_local_adapter.py tests/unit/loom/queue/test_queue_preflight.py tests/unit/loom/queue/test_managed_resources.py
    uv run pytest tests/unit/loom/pipeline/execution/test_resource_admission.py tests/contracts/test_queue_managed_resources_contract.py tests/contracts/test_workspace_coordination_contract.py
    uv run --extra config pytest tests/contracts/test_queue_config_contract.py
    uv run pytest tests/integration/queue/test_managed_local_controller.py tests/integration/queue/test_sqlite_repository.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: regressing Phase 1 release ordering, losing a partially renewed
  assignment, persisting fencing/binding data, over-generalizing the provider,
  and claiming crash safety that in-memory ownership cannot provide.
- Review focus: the provider surface contains no discovery/recovery mechanism;
  schema-v1 and non-local compatibility remain unchanged; authored schema-v2
  records are the only new config form; persisted assignment/log evidence is an
  exact allowlist; and scalar/assignment renewal, process termination, reverse
  release, and refill occur in that causal order for either-class loss. Confirm
  preflight performs no authority mutation or DDL.
- Stop if: the coordination protocol cannot distinguish a required failure;
  safe process shutdown needs a new durable recovery state; a supported platform
  cannot provide queue-owned logs through the process-runner boundary; or new
  queue/authority DDL appears necessary. Also stop rather than adding provider
  discovery, a durable live token, reattachment, a renewal daemon, or a second
  owner of release state. Return the concrete failing path and evidence to the
  manager; do not broaden the phase.
- Accepted debt and revisit trigger: authored inventory and live-only tokens are
  accepted until dynamic placement or restart recovery is a current consumer;
  controller death/unkillable process remains explicit recovery-needed risk.

## Executor Handoff

- Read section range: this entire phase plan plus planning requirements `FR-6`
  through `FR-12` and decisions `A-2` through `A-7`.
- Safe implementation slices: execute slices 1-5 in order and keep assignment
  types queue-local; internal commit grouping is discretionary.
- Decisions not to revisit: no resource-instance schema, registry/recovery hook,
  dynamic discovery, vendor semantics, per-renewal queue write, arbitrary
  binding, or crash-time guarantee.
- Conditions requiring manager action: any stop condition, change to Phase 1's
  dispositions/guards, or need to expose provider-private state durably.

## Workflow State

- Manager preparation: complete on 2026-08-17 against `e47ed77`; Phase 1 merge,
  plan/manifest consistency, worktree isolation, and expanded-route triggers
  verified
- Expanded planning: complete on 2026-08-17; fixed the public provider boundary,
  schema-v2 authored record boundary, durable evidence allowlist, and causally
  coupled renewal/compensation checks without adding recovery or DDL
- Implementation: complete on 2026-08-18; added the queue-local static
  assignment protocol/providers, schema-v2 normalization and read-only
  preflight, coupled local lifecycle handling, queue-relative logs, and
  phase-scoped tests
- Refiner: completed on 2026-08-18 for the qualified local assignment cleanup
  and evidence-projection blocker; retries now skip successfully released
  layers, pre-start compensation attempts both layers, and evidence is
  projected before process start
- Manager correction: completed on 2026-08-18 for the public import/immutable
  record boundary; assignment imports remain cheap and public request/binding
  mappings cannot be mutated after construction
- Final manager correction: completed on 2026-08-18 for the remaining accepted
  provider/config/preflight and coupled-renewal validation boundary; invalid
  static inventory is rejected, preflight proves lease capabilities read-only,
  and independent scalar/assignment renewal plus real-SQLite exclusivity have
  focused coverage
- Pre-submit gate: complete on 2026-08-18 at `3b8693d`; `make validate-pr`
  passed Ruff, Pyright, the default and config-extra suites, and package build.
  A fresh `make test-summary` receipt passed with 2,173 tests passed, zero
  failures/errors, and three config-extra skips
- Independent review: completed on 2026-08-18; not merge eligible because a
  supported multi-slot cleanup retry can report ownership loss for an
  already-released slot while another slot remains transiently unreleased. The
  maintainer-authorized correction now gives unfinished failures precedence;
  manager verification and the focused regression test close the finding
- Blocker corrections: 4 total; the first 3 consumed the normal budget and the
  maintainer explicitly authorized one bounded correction for the independent
  review finding
- PR and merge: PR `#210` passed required CI and squash-merged into `develop`
  as `7187829` on 2026-08-18; worktree and local/remote phase branch removed

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `src/loom/queue/assignments.py`; updated queue exports, config normalization, local dispatch lifecycle, and preflight; added or updated Phase 2 queue unit, config-contract, preflight, and managed-local integration coverage. Qualified corrections added layer-aware cleanup and strict evidence projection, restored cheap immutable public records, validated injected/authored static inventory and authority capabilities, and made scalar/assignment renewal independent while preserving fail-closed deadlines. |
| Tests added or updated | Assignment/provider tests cover ordered selection, partial compensation, discriminator safety, injection validation, and immutable public mappings. Local tests cover binding conflict, pre-start and terminal cleanup, evidence rejection, independent renewal, ownership loss, and deadline termination. Config/preflight tests cover v1/v2, inventory/collision rejection, read-only limits, and missing capabilities. Real-SQLite integration proves cross-instance slot exclusivity/capacity; controller integration covers cancellation and handle-commit compensation with static assignments. Package coverage asserts facade exports and import-light CLI help. |
| Validated revision/tree state and evidence | Implementation tree based on `a3fba14`, validated at `3b8693d`. The executor-generated receipt exposed the import-light regression and was superseded after correction. Final manager `make validate-pr` passed Ruff, Pyright, the default and config-extra suites, and package build. The fresh `build/test-summary.md` receipt passed: 2,173 passed, zero failures/errors, and three config-extra skips. |
| Validation-relevant changes after evidence | Documentation-only workflow-state and completion-record updates after the validated implementation revision; no source, test, dependency, build, or validation configuration changed. |
| PR, review, and merge | Independent review found one product blocker; the maintainer-authorized correction and manager verification closed it. PR `#210` passed required CI and squash-merged into `develop` as `7187829`. |
| Residual risk and cleanup | No known blocker. Mixed multi-slot release now preserves retryable/internal failure precedence until every slot is accounted for. Crash-time recovery, reattachment, provider discovery, and background renewal remain intentionally out of scope. |
