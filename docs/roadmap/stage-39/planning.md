# Roadmap Stage 39 Planning: Independent Resource Accounting And Enforcement

Status: evidence-backed draft; detailed design and independent review pending
Roadmap stage: 39
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-39-resource-policy-plan`
at `0e14d503cc2932207aece0765cb2da111cf2154b`, branch
`agent/stage-39-resource-policy-plan`; relevant dirty paths before drafting: none.
Planning route: expanded, because this changes runtime options, persisted
placement/recovery meaning and cross-backend resource controls.
Current gate: functionality accepted; source reconciliation and minimum design
Blockers: no user decision requested; design/readiness not yet claimed

## Current State

The maintainer's 2026-09-08 implementation request includes generic separation
of resource demand, scheduling accounting and enforcement. This is separate from
rphys Stage 81's causal diagnostics and Stage 85's deployment ownership. Existing
Stage 38 delivery and the original dirty Loom checkout remain preserved.
This work is not a prerequisite for the managed CPU diagnostic proof. A physical
experiment can depend on it only through an explicit published prerequisite.

| Gate | Locked result | Remaining work |
| --- | --- | --- |
| Functionality | Independent accounting/enforcement; explicit none; truthful delegation; preserve lifecycle ownership | Resolve concrete current runtime/placement/adapter propagation |
| Minimum design | Reuse existing demand, claims, capabilities, timeout and backend mappers | Finalize defaults, public shape and retained-run migration from the observed source |
| Validation / phase shaping | Distinguish selections through real admission/command boundaries | Complete finite supported matrix and independently reviewable phase cards |
| Quality / implementation | Not ready; no runtime edits | Expanded design/plan review, then normal Loom phase workflow |

## Evidence And Scope

| Existing owner | Current behavior | Consequence for this work |
| --- | --- | --- |
| `pipeline/resources.py::ResourceRequest`, `ResourceEntry` | Schema-2 entries hold kind, amount, unit and attributes | One authoritative demand representation; do not create CPU/RAM/GPU amount copies in each policy |
| `pipeline/runtime/options.py::RunOptions`, `StageRuntimeOptions` | Resource, execution, environment, reliability and adapter options compose into exact runtime choices | Add generic policy through these existing composition/serialization owners |
| `queue/local_daemon_runtime.py::_runtime_payload` | Every runtime resource kind currently needs a configured planner; authored/runtime resources resolve into persisted placements | Account only selected demand kinds without dropping unselected original intent |
| `queue/local_daemon_runtime.py::_stage_placement_policy` | Current default resource demand includes one CPU | Explicit empty/GPU-only accounting must not accidentally reintroduce CPU claims through this default |
| `pipeline/runtime/placement.py::ResolvedStagePlacement` | Immutable schema-2 placement and fingerprint feed admission, recovery and SLURM mapping | Policy must survive this boundary and replay comparison; command generation cannot reconstruct a different selection |
| `pipeline/runtime/placement.py::resolve_stage_placement` and `ResolvedStagePlacement.from_dict` | Planners own authored/default/runtime demand resolution; decoding currently reconstructs scheduling requests for every resource entry | Apply accounting selection after semantic demand resolution; persist the selection so decoding cannot recreate excluded claims |
| `queue/local_daemon_runtime.py` schema-2 prepared payload | Exact runtime/placement payload participates in replay comparison | A policy change needs an explicit retained-payload version/read/upgrade rule, not only new Python defaults |
| `pipeline/runtime/capabilities.py::ResourceCapability`, `ResourceEnforcementExpectation` | Metadata already distinguishes enforced, best-effort, not-enforced and not-applicable | Extend truthful reporting at its current owner; static capability is not measured host enforcement |
| `pipeline/executors/apptainer/commands.py::_append_resource_limits` | `cpu_memory_enforcement=runtime/scheduling_only` selects CPU/RAM flags from mapped container resource intent | Replace the adapter-specific switch after generic policy and consumers exist |
| `pipeline/executors/_reliability.py`, reliability policy | One existing timeout policy and metadata path | Do not introduce a second deadline model merely to nest timeout under a new config key |
| `pipeline/executors/slurm/resources.py::map_slurm_resources` | Maps request entries into SBATCH directives | Scheduler request and inner process enforcement are different owners |
| `pipeline/executors/slurm/ready_stage.py::map_ready_stage` | Maps the persisted placement request and rejects unmappable hard requirements | Preserve hard semantics, profile identity and request digest on delegated execution |
| `pipeline/executors/slurm/planning.py` | Whole-run/stage job planning also maps resource directives | Do not update only ready-stage delegation while silently changing other supported routes |

Current consumers are native managed agents, direct container executors,
protected SLURM ready-stage and existing SLURM planning, their dry-run/preflight
views, resume/recovery readers and maintained configurations/tests. Agent offered
capacity stays with the deployed provider/role and is not rewritten by a job.

Non-goals: new schedulers/providers, distributed/gang execution, hardware
discovery, hostile-code isolation, live migration, modifying host cgroup/D-Bus
settings, scientific changes, or Stage 85 role-schema implementation. No real
SLURM/GPU result is inferred from command construction or capability metadata.

## Minimum Useful Change

Declare each demand once. Resolve two independent selections against it:

1. Demand kinds used by Loom when admitting work against capacity.
2. Controls requested for execution, with their actual enforcing owner recorded.

The same job may account for GPU only while applying GPU binding and a timeout,
CPU/RAM controls, or no additional controls. It must remain inspectable which
demands were not accounted or enforced. Removing all resource declarations to
avoid unavailable cgroups is not equivalent: that loses useful scheduling intent.

Reuse current resource and timeout models. A new policy is justified because
the existing adapter-specific CPU/RAM switch cannot express independent GPU,
CPU/RAM and timeout behavior across backends. No global registry, second resource
schema, alternate scheduling engine or new lifecycle store is required.

## Functional Requirements

| ID | Behavior | Boundary / validation |
| --- | --- | --- |
| FR-39-01 | Offered capacity, job demand, accounting and enforcement remain separate; effective demand amounts have one authority | Config composition, placement and replay preserve all four meanings |
| FR-39-02 | Accounting can select GPU only, another supported subset, all demands or none without imposing limits | Actual admission/claim tests; excluded CPU/RAM demand does not block GPU-only work |
| FR-39-03 | Enforcement selection is independent, including explicit none; unmapped/absent demand creates no invented limit | Resolved runtime to actual argv/environment/deadline tests |
| FR-39-04 | Explicit requested unsupported enforcement fails with actionable explanation; no silent downgrade | Capability/preflight/executor failure cases |
| FR-39-05 | No-enforcement preserves cancellation, assignment ownership, deadlines needed for control-plane protocols and process cleanup; it disables only selected job limits | Existing containment/lifecycle tests plus explicit no-job-timeout case |
| FR-39-06 | SLURM requests/delegation are distinct from inner limits; no duplicated container cgroups | SBATCH and nested launch assertions for supported SLURM routes |
| FR-39-07 | Metadata reports demand, accounting, requested/delegated/applied/unavailable controls and actual mechanism without overstating guarantees | Public inspection/preflight and runtime metadata tests |
| FR-39-08 | Existing composed/persisted options and retained work have an explicit migration/recovery rule; old adapter switch is retired only with migrated consumers | Codec, profile, restart/replay and maintained example tests |

## Functionality Agreement

The attachment explicitly authorizes FR-39-01..08's behavior. GPU accounting is
reservation bookkeeping, not VRAM or compute isolation. GPU binding controls
visibility/selection, not a security boundary. Excluding CPU/RAM from accounting
allows oversubscription; this is deliberate and must be reported honestly.

Unmapped demand imposes no extra restriction. Selecting no additional enforcement
cannot remove inherited host or scheduler constraints. Actual control support is
backend-specific and must not be guessed from a generic resource label.

## Behavior Baseline And Design Questions

The following are named source-reconciliation tasks, not delegated product choices:

- Finalize the smallest typed policy placement in current runtime options,
  including per-stage overrides, exact collection/absent semantics and defaults.
  Do not conflate an omitted override with an explicit empty selection.
- Preserve all effective demand for provenance while deriving accounting claims
  from the selected subset. Account for the existing default-CPU path and current
  unsupported-planner check. A selection without a demand must not invent one.
  A resource planner also owns semantic refinement/unit rules: excluding a kind
  from capacity accounting does not justify bypassing its demand-resolution
  invariant. Separate semantic normalization from availability/claim validation.
  The current decoder rebuilding all `scheduling_requests` is a required negative
  regression: a GPU-only prepared placement must remain GPU-only after decode.
- Trace the policy through exact resolved runtime, persisted placement,
  assignment launch, preparation/replay and adapter command generation. Runtime
  receipt metadata must distinguish selected intent from applied control.
- Keep job timeout in the existing reliability owner, with one declared amount
  and explicit enable/disable behavior. Control-plane/cleanup timeouts are not job
  resource limits and stay active.
- Distinguish SLURM allocation requests from additional controls inside the
  allocation. An SBATCH allocation may result in scheduler-imposed constraints;
  no-enforcement must not promise an unconstrained allocation. Map every explicit
  hard request or reject it before submission, preserving current profile/digest
  authority and no silent dropped semantics.
- Decide the narrow supported old-runtime/placement read and retained-run
  migration from actual producers; do not create a generic compatibility engine.
  Source-shaped default behavior alone must not silently change retained claims
  or launch controls on restart.

The syntax in the user attachment is illustrative. Final public shape, default
behavior and durable migration must be fully specified and independently reviewed
before writing runtime code. A new amount field for the same demand is not an
acceptable solution to an adapter handoff gap.

## Complexity Delta

| Addition | Current necessity | Simpler alternative / disposition |
| --- | --- | --- |
| Independent accounting/enforcement policy | Current GPU scheduling with unavailable local cgroups | Required; existing CPU/RAM-only switch cannot represent it |
| Policy in existing runtime/placement representations | Preparation, restart and execution must agree | Required at current durable boundary; no new policy store |
| Mechanism/delegation metadata | Existing capability labels can overstate what actually happened | Extend current metadata; no separate audit database |
| Additional scheduler/provider framework | No current need | Defer |
| Second timeout schema | Existing reliability owner already serves all consumers | Reject duplication |

## Examples And Validation

| Case | Discriminating behavior |
| --- | --- |
| GPU-only accounting; CPU/RAM demand also present | GPU admission works without consuming/checking CPU/RAM capacity; original demand remains inspectable |
| Accounting includes CPU/RAM, enforcement none | Capacity admission still applies; direct container launch adds no CPU/RAM limit flags |
| GPU accounting, CPU enforcement and enabled timeout | Each axis reaches its own real owner; GPU binding is not added merely because GPU was accounted |
| Explicit empty accounting | Existing default CPU does not reappear as a hidden claim; supported no-resource lifecycle remains owned |
| Enforcement selection with no corresponding demand | No fabricated amount, limit, mask or deadline |
| Unsupported explicitly requested mechanism | Clear failure with requested control, backend limitation and correction guidance |
| SLURM allocation and inner container | Correct SBATCH request; no duplicate inner cgroups; delegated/inherited constraints reported accurately |
| Retry/restart of retained prepared work | Selected policy and ownership remain identical or migration fails explicitly before effects |
| No job enforcement with cancellation/cleanup | Owned children terminate and reservations release under existing lifecycle rules |

Use existing runtime-options/profiles/capabilities, placement/managed-runtime,
daemon admission/recovery, Apptainer/Singularity command/executor, reliability and
SLURM planning/ready-stage tests. Combined cases are required only where policy
axes meet at admission or launch. A fixture for a real supported no-cgroup
container smoke may prove launch and timeout behavior; it does not prove hard
CPU/RAM enforcement on the host. Live SLURM and hard GPU isolation are not claimed.

## Phase Shaping And Quality Gate

Do not create execution cards before the named minimum-design tasks are resolved.
Likely merge boundaries are a complete managed accounting/config/replay change,
then generic executor controls and adapter migration, with SLURM delegation
kept separate only if each prior state remains supported. No preferred phase
count overrides atomic durable migration or a usable current consumer.

Required local gates for each implemented Loom phase remain `make validate-pr`
and `make test-summary`; independent correctness review is required for these
public/durable/runtime changes. Hosted CI remains disabled. Normal Loom isolated
phase branches/PRs target develop, with verified merge and exact cleanup.

Current quality gate: draft, not implementation-ready. No runtime tests or
resource guarantees are claimed. Next action is concrete current-owner design,
then the expanded independent design/plan review and approved phase packet.
