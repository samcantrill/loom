# Phase 2 Execution Plan: Whole-Run Queue Resource Accounting And Controls

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 39, Phase 2
- Manifest: `docs/roadmap/stage-39/implementation-plan.md`
- Branch: `agent/stage-39-p2-queued-resource-policy`
- Worktree: `stage-39-p2-queued-resource-policy` under the manifest's root
- Base revision: published develop after Phase 1's remote merge; source inventory
  at `719e016c6fe5e1ec3e70994bca6b3716964fc200`
- PR target: develop
- PR title: `feat(queue): separate queued resource accounting and binding policy`
- Dependencies: final concrete plan approved; Phase 1 remote merge remains required
- Workflow path: expanded; public provider contract, durable identity and lifecycle
- Blockers: predecessor merge; no runtime changes yet

## Objective And Context

Deliver FR-39-01..05 and FR-39-07..08 on the older opaque whole-run queue API,
reusing Phase 1's policy semantics. Scheduling/accounting can use a logical GPU
pool while launch adds no binding, without losing reservation renewal/release.
Eligibility, custom selection, scalar/concrete admission, binding and replay
consumers must all agree on that choice.

For FR-39-06, preserve existing delegated/preprepared SLURM snapshots; Phase 1
owns allocation/inner-control mapping. The queue never rewrites opaque argv to
remove limits or infer scheduler requests. No later resource-policy foundation,
provider framework or queue migration phase is required.

## Current Source And Harness

- `src/loom/queue/models.py::LaunchContract`,
  `service.py::{QueueEnqueueRequest,QueueService._admit}` and `_sqlite.py`
  own enqueue/record identity.
  Read `docs/features/queue.md` and `docs/structure.md`.
- `selection.py::{_is_eligible,_evaluate_selection}` and
  `QueueSelectionCandidate.resources`, `controller.py::_advisory_available_resources`
  consume demand before dispatch. Retain current bounded page/cycle budgets.
- `controller.py::{_select_and_acquire_for_pool,_safe_dispatch,_apply_dispatch_result}`
  own claim and existing not-started invalid/unsupported → FAILED disposition.
- `local.py::{LocalQueueDispatchAdapter,_resource_admission_request,
  _merge_assignment_environment}` own scalar/concrete admission and actual spawn.
- `assignments.py::LaunchEnvironmentBindings`, `StaticSlotAssignmentProvider`,
  `queue/gpu/local.py::_LocalGpuAssignmentProvider` and maintained
  `examples/operations/managed-local-queue/paired_assignment_provider.py` own
  authoritative binding identities. NoOp owns no binding. GPU/paired acquisition
  rejects empty demand; reuse the existing no-assignment path for none.
- Harness: Python 3.12, locked `uv`, existing queue fixtures, fake assignments,
  ordinary local shell processes and SQLite; no hardware or new dependencies.

## Scope

In scope: policy-aware enqueue/contract, all whole-run accounting consumers,
attributed bindings and maintained producers, legacy inspection and pre-launch
disposition, lifecycle-safe errors, docs/examples and relevant tests.

Out of scope: pipeline policy redesign, semantic/logical name translation,
opaque command rewriting, new amounts/providers, global DB migration, automatic
old live-work adoption, Stage 85 probes, rphys source, physical jobs and live SLURM.

Assumption: existing logical integer demand keys remain the whole-run namespace;
`lab-accelerators` is not implicitly the pipeline `gpu` kind.

## Fixed Contracts And Private Discretion

- `QueueEnqueueRequest` and `LaunchContract` carry the shared `ResourcePolicy`.
  At new enqueue compose defaults all/empty and persist effective policy plus
  exact post-demand `resource_selection` in admission/replay identity. Full integer
  resources remain the only amounts. Reuse Phase 1 semantics without executor imports.
- Eligibility, custom `QueueSelectionCandidate.resources`, advisory subtraction
  for active claims, scalar lease requests and concrete assignment requests use
  one selected accounting view. Full demand remains inspectable. Excluded demand
  cannot block early selection or reappear at dispatch.
- Empty accounting uses the existing no-assignment path even with a GPU/paired
  provider configured. Never call invalid empty acquisition or invent a hidden
  reservation. Queue ownership, supervision and cleanup remain active.
- `LaunchEnvironmentBindings.resource_names: Mapping[str, str]` maps emitted
  environment names to logical resource keys. Environment and attribution maps
  are immutable/detached; attribution references existing environment keys.
  Unattributed external-provider values remain representable. Select added
  bindings by authoritative attribution, never variable spelling, physical
  member labels, safe_evidence or a guessed sole GPU request.
- Static-slot, GPU and paired-example providers populate attribution from their
  existing resource-name owner and preserve it through renewal. NoOp fabricates
  none. Add no protocol methods or duplicated amounts.
- Enforcement empty ignores provider-added values but keeps reservation,
  renewal/fencing/release. Explicit binding requires matching authoritative
  assignment/support; missing attribution/support fails before spawn with nested
  actionable context and existing pre-start release. Excluded accounting cannot
  secretly reserve resources to supply enforcement.
- Preserve authored argv/environment and inherited constraints. This opaque local
  route supports provider bindings, not inferred CPU/RAM flags or an argv parser.
  Preprepared SLURM identity remains upstream-owned. Existing timeout/supervision
  and control-plane deadlines stay separate.
- Only `LaunchContract` becomes schema 3. Keep `QUEUE_RECORD_SCHEMA_VERSION=2`
  and `QUEUE_DB_SCHEMA_VERSION=2`. The codec reads exact old schema-2 contracts
  for inspection and reproduces their original fields/serialization without
  policy injection, preserving enclosing admission digests. Legacy means no
  effective policy, not new defaults.
- Fresh constructors/enqueue produce schema 3. `QueueService._admit` rejects
  supplied legacy contracts before repository writes. For retained QUEUED legacy
  items, compatibility disposition bypasses capacity/custom preference filtering
  inside the existing bounded page. Claim only queue ownership/attempt guards;
  return NOT_STARTED, INVALID_OR_UNSUPPORTED, cleanup NOT_REQUIRED. Existing
  `_apply_dispatch_result` persists FAILED and continues within cycle budgets
  before scalar admission, assignment or spawn. Preserve nested contract/digest;
  normal outer claim/attempt/failure/audit updates are allowed. Respect races;
  no unbounded scan or new lifecycle state.
- Direct adapter dispatch also rejects legacy before resource/launch effects.
  Errors name the version and instruct operators to preserve artifacts,
  finish/cancel old active work in a compatible pinned environment and enqueue a
  fresh identity. Never restart/adopt old active work, edit versions or erase
  records. Ordinary queue inspection remains available.
- Use existing metadata owners for effective policy, concrete selection and the
  Phase 1 `resource_controls` shape/dispositions. Actual supplied binding is launch
  evidence, not isolation. Leases retain reservation evidence; no raw capabilities
  or binding tokens enter controls. Old missing metadata is unreported; existing
  structured diagnostics carry full supported nested causes.
- Private legacy/current representation, helpers, merge wiring and fixtures remain
  discretionary. No compatibility registry, state store or migration CLI.

## Proportionality

Extend current queue/provider owners rather than add a scheduler. Attribution is
needed because producers know logical identities discarded by flattening; opaque
names cannot safely recover them. Narrow legacy reading preserves inspection and
digests; existing FAILED prevents incompatible bounded-page entries from stranding
new work. General migrations, foreign-provider adaptation, allocation inference
and arbitrary external controls are deferred.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer / consequence | Coverage |
| --- | --- | --- | --- | --- |
| One accounting view | Enqueue projection and existing selection/admission | Excluded CPU blocks GPU work or returns as a claim | Custom candidate, advisory and actual requests agree |
| Authoritative binding | Binding codec, provider and launch boundary | Flat provider/physical label yields wrong mask | Logical attribution/renewal, missing-support error and release |
| No hidden reservation | Existing adapter no-assignment path | GPU provider rejects empty request or secretly reserves | Account-none avoids provider acquire; queue lifecycle retained |
| Retained identity | Contract codec and enqueue admission | New default changes old digest or policy change replays as identical | Old exact round trip, new replay/conflict, legacy admission no writes |
| Bounded legacy disposition | Selection/controller and existing result reducer | Oversized old item occupies page repeatedly | One queue-only FAILED before resource/spawn, current work progresses |
| Honest lifecycle/evidence | Dispatch/process and metadata owner | Binding-none loses lease or claims isolation | Renewal/release without binding, unchanged authored snapshot |

## Implementation Slices

1. Extend enqueue/contract using shared policy/projection, schema-2 inspection and
   schema-3 identity. Add old-writer/replay fixtures; no global version change.
2. Apply accounting to eligibility/custom selection, advisory, scalar and concrete
   admission, including account-none with a configured provider.
3. Add attribution and migrate all maintained producers. Select added environment
   independently; preserve snapshots and prove normal/error-path release.
4. Implement bounded legacy claim-to-FAILED and direct pre-effect rejection.
   Cover oversized old demand, mixed pages and existing concurrency protections.
5. Align docs/examples/metadata, run causal integrations, full stable-tree gates
   and independent correctness review before remote merge.

## Test And Validation Plan

| Suite | Required or deferred | Behavior/risk and minimum oracle |
| --- | --- | --- |
| Package / contract | required | Public API/import tests, `test_queue_records_contract.py`, `test_queue_managed_resources_contract.py`: lightweight policy, immutable attribution, isolated LaunchContract version |
| Selection / controller | required | `tests/unit/loom/queue/test_scheduler.py`, `tests/integration/queue/test_managed_local_controller.py`: excluded CPU demand cannot block default/custom selection or later advisory capacity; actual dispatch agrees |
| Providers / adapter | required | `test_assignments.py`, local GPU contract/units, `test_example_paired_assignment_provider.py`, `test_local_adapter.py`: static/GPU/bundle attribution/renewal; actual launch environment; unchanged authored values; binding-none retains/releases leases; missing attribution rejects and releases before spawn |
| Empty accounting | required | Configured GPU/paired dispatch takes no-assignment path, never calls provider acquire, retains queue supervision/cancel/cleanup, and cannot invent a reservation for explicit binding |
| Retained identity | required | Queue records and `tests/integration/queue/test_sqlite_repository.py`: exact old schema-2 digest/inspection, new exact replay and changed-policy conflict, supplied legacy fresh admission writes nothing |
| Legacy lifecycle | required | Existing scheduler/controller/adapter owners: mixed bounded old/new queue with old demand beyond capacity and adverse custom preference still gets one queue-only FAILED before resource/spawn; later current work progresses; nested old bytes unchanged; direct guard works |
| E2E / examples | required | Existing queue CLI/inspection and maintained examples: old inspection usable, migration guidance actionable, logical namespace explicit, no opaque command rewrite |
| Integrated regression | required | Full gates preserve lifecycle/replay, delegated SLURM snapshots and Phase 1 policy; no eager factory checking |
| Physical / live scheduler | deferred | Fake resources and bounded ordinary shell processes only; no real GPU/SLURM execution, host changes or hardware-isolation proof |

Targeted commands use the worktree's locked environment and current test owners:

    uv run --locked --group dev pytest tests/contracts/test_queue_records_contract.py tests/unit/loom/queue/test_scheduler.py tests/unit/loom/queue/test_assignments.py tests/unit/loom/queue/test_example_paired_assignment_provider.py tests/unit/loom/queue/test_local_adapter.py
    uv run --locked --group dev pytest tests/contracts/test_local_gpu_assignment_provider.py tests/unit/loom/queue/gpu/test_local.py tests/integration/queue/test_managed_local_controller.py tests/integration/queue/test_sqlite_repository.py tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

Record exact revision/tree and required-case results. Later relevant changes make
receipts stale; planning diff checks are not runtime proof.

## Risks, Review, And Stops

- Independently review current/upstream assumptions and actual diff: schema
  isolation, old digest, bounded legacy handling, all accounting consumers,
  attribution and release. Phase 1 review does not cover this queue migration.
- Canonical expanded budget: one executor, at most one qualified refiner, three
  total scoped blocker corrections; independent implementation review after
  manager pre-submit checks. Optional hardening is not a gate.
- Stop for broken old inspection/digests, a required route needing opaque command
  rewriting/new machinery, material upstream contract change, exhausted correction
  budget or proposed physical execution.
- Accepted debt: flat external providers remain usable with enforcement-none;
  explicit binding needs their small attribution update. Old active work needs
  its pinned environment, not automatic adoption.

## Executor Handoff

Read this card, manifest shared contracts and current Loom AGENTS/workflow. Reuse
Phase 1's implementation. Own queue policy/providers and linked tests/docs; you
are not alone and must preserve others' edits. No children, new mechanisms,
default changes or physical jobs. Return implementation and targeted evidence;
manager owns subsequent full gates/PR/review/merge through the workflow.

## Workflow State

- Manager preparation: source inventory and two-phase dependency recorded
- Expanded planning: EDR-39-02 confirmed; packet review passed with no Phase 2
  findings; final plan and concrete compatibility rules approved
- Implementation / refiner / pre-submit / independent implementation review: not started
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | not started |
| Tests added or updated | not started |
| Validated revision/tree state and evidence | no runtime evidence |
| Validation-relevant changes after evidence | not applicable |
| PR, review, and merge | pending |
| Residual risk and cleanup | no live upgrade or physical proof; no phase tree yet |
